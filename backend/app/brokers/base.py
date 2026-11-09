"""Broker adapter interface and the app's own broker-neutral types.

Nothing outside `app/brokers/` ever sees broker-specific JSON: adapters translate to and
from these types. Money and prices are always `Decimal`.

Order placement safety: `BrokerAdapter.place_order` is final. For any non-paper adapter it
refuses to send an order unless the adapter was created with `live_enabled=True` AND the
platform setting `TRADING_MODE=live`. Only the order manager (after the risk engine) may
call it; the order manager sets `live_enabled` from the user's own trading mode.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Literal

import pandas as pd

from app.core.config import get_settings

Purpose = Literal["trading", "data"]
Capability = Literal["trading", "data", "historical", "options"]
Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT", "SL", "SL-M"]
Product = Literal["INTRADAY", "DELIVERY", "MARGIN"]
OrderState = Literal["OPEN", "TRIGGER_PENDING", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"]
Timeframe = Literal["1m", "5m", "15m", "1h", "1d"]

TIMEFRAME_SECONDS: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}


# ---------------------------------------------------------------- errors


class BrokerError(Exception):
    """Base error for anything a broker adapter raises. Messages never contain secrets."""


class BrokerAuthError(BrokerError):
    """Credentials missing, wrong or expired."""


class BrokerNotSupported(BrokerError):
    """This adapter does not support the requested capability (yet)."""


class LiveTradingBlocked(BrokerError):
    """A live order was attempted while live trading is not enabled."""


class OrderRejected(BrokerError):
    """The broker (or paper engine) rejected the order."""


class RateLimited(BrokerError):
    """Broker rate limit hit."""


# ---------------------------------------------------------------- credentials


@dataclass(frozen=True)
class FieldSpec:
    """One credential field. The dashboard builds the 'Add broker' form from these."""

    name: str  # e.g. "client_id", "access_token"
    label: str  # shown in the form
    secret: bool = True  # secrets are encrypted and only last4 is ever shown
    help: str = ""  # where to find this value
    required: bool = True


@dataclass(frozen=True)
class BrokerCredentials:
    """Decrypted credentials, split by purpose. Never log or return these."""

    trading: dict[str, str] = field(default_factory=dict)
    data: dict[str, str] = field(default_factory=dict)

    def for_purpose(self, purpose: Purpose) -> dict[str, str]:
        return self.trading if purpose == "trading" else self.data

    def __repr__(self) -> str:  # never print values
        return f"BrokerCredentials(trading={sorted(self.trading)}, data={sorted(self.data)})"


# ---------------------------------------------------------------- results


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    expires_at: datetime | None = None

    def __repr__(self) -> str:
        return f"TokenSet(access_token=****, expires_at={self.expires_at!r})"


@dataclass(frozen=True)
class Funds:
    available: Decimal
    used_margin: Decimal = Decimal(0)
    total: Decimal | None = None


@dataclass(frozen=True)
class ConnectionReport:
    ok: bool
    message: str
    purpose_ok: dict[str, bool] = field(default_factory=dict)  # {"trading": True, "data": False}
    funds: Funds | None = None
    token_expires_at: datetime | None = None


@dataclass(frozen=True)
class Instrument:
    broker: str
    exchange: str
    segment: str
    symbol: str
    broker_token: str
    name: str | None = None
    lot_size: int = 1
    tick_size: Decimal = Decimal("0.05")
    expiry: date | None = None
    strike: Decimal | None = None
    option_type: Literal["CE", "PE"] | None = None


@dataclass(frozen=True)
class Tick:
    exchange: str
    symbol: str
    ts: datetime  # exchange time, timezone-aware
    ltp: Decimal
    volume: int = 0  # cumulative traded volume for the day
    last_qty: int = 0
    # Day statistics from the exchange, when the feed sends them (real feeds do; the simulator not).
    day_open: Decimal | None = None
    day_high: Decimal | None = None
    day_low: Decimal | None = None
    prev_close: Decimal | None = None


# ---------------------------------------------------------------- orders


@dataclass(frozen=True)
class OrderRequest:
    order_ref: uuid.UUID  # client-side id: retries must reuse it, never double-place
    exchange: str
    symbol: str
    side: Side
    qty: int
    order_type: OrderType = "MARKET"
    product: Product = "INTRADAY"
    price: Decimal | None = None  # LIMIT and SL
    trigger_price: Decimal | None = None  # SL and SL-M
    strategy_id: str | None = None

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError("qty must be positive")
        if self.side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if self.order_type in ("LIMIT", "SL") and (self.price is None or self.price <= 0):
            raise ValueError(f"{self.order_type} order needs a positive price")
        if self.order_type in ("SL", "SL-M") and (
            self.trigger_price is None or self.trigger_price <= 0
        ):
            raise ValueError(f"{self.order_type} order needs a positive trigger_price")
        for name in ("price", "trigger_price"):
            v = getattr(self, name)
            if v is not None and not isinstance(v, Decimal):
                raise TypeError(f"{name} must be Decimal")


@dataclass(frozen=True)
class OrderChanges:
    qty: int | None = None
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    order_type: OrderType | None = None


@dataclass(frozen=True)
class OrderAck:
    order_ref: uuid.UUID
    broker_order_id: str
    status: OrderState
    message: str = ""


@dataclass(frozen=True)
class OrderStatus:
    order_ref: uuid.UUID | None
    broker_order_id: str
    status: OrderState
    exchange: str
    symbol: str
    side: Side
    qty: int
    filled_qty: int = 0
    avg_price: Decimal | None = None
    message: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True)
class BrokerPosition:
    exchange: str
    symbol: str
    product: Product
    qty: int  # positive long, negative short, 0 closed today
    avg_price: Decimal
    ltp: Decimal | None = None
    realised_pnl: Decimal = Decimal(0)
    unrealised_pnl: Decimal = Decimal(0)


# ---------------------------------------------------------------- rate limiting


class AsyncRateLimiter:
    """Allow at most `rate` calls per `per` seconds (sliding window). One per adapter instance."""

    def __init__(self, rate: int, per: float = 1.0) -> None:
        self.rate = rate
        self.per = per
        self._calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._calls = [t for t in self._calls if now - t < self.per]
                if len(self._calls) < self.rate:
                    self._calls.append(now)
                    return
                await asyncio.sleep(self.per - (now - self._calls[0]))


# ---------------------------------------------------------------- adapter


class BrokerAdapter:
    """Base class for every broker. Subclasses override what they support.

    One instance per user broker account, built with that account's decrypted credentials.
    """

    key: ClassVar[str]
    display_name: ClassVar[str]
    supports: ClassVar[frozenset[Capability]]
    credential_fields: ClassVar[dict[Purpose, list[FieldSpec]]]
    auth_type: ClassVar[Literal["none", "api_key", "oauth"]] = "api_key"
    is_paper: ClassVar[bool] = False
    docs_url: ClassVar[str | None] = None

    def __init__(self, credentials: BrokerCredentials | None = None, *, live_enabled: bool = False):
        self.credentials = credentials or BrokerCredentials()
        self.live_enabled = live_enabled

    def __repr__(self) -> str:
        return f"<{type(self).__name__} key={self.key} live_enabled={self.live_enabled}>"

    # ---- helpers

    def require(self, purpose: Purpose) -> dict[str, str]:
        """Return the credentials for `purpose`, or raise if a required field is missing."""
        creds = self.credentials.for_purpose(purpose)
        missing = [
            f.name
            for f in self.credential_fields.get(purpose, [])
            if f.required and not creds.get(f.name)
        ]
        if missing:
            raise BrokerAuthError(f"{self.display_name}: missing {purpose} credentials: {missing}")
        return creds

    def _not_supported(self, what: str) -> BrokerNotSupported:
        return BrokerNotSupported(f"{self.display_name} does not support {what} yet")

    # ---- auth

    async def login_url(self, state: str) -> str | None:
        """OAuth brokers: URL of the broker login page. Others: None."""
        return None

    async def complete_login(self, callback_params: dict[str, str]) -> TokenSet:
        raise self._not_supported("OAuth login")

    async def test_connection(self) -> ConnectionReport:
        raise self._not_supported("connection test")

    # ---- trading

    async def place_order(self, req: OrderRequest) -> OrderAck:
        """Final: checks the live-trading gate, then calls `_place_order`. Do not override."""
        if not self.is_paper:
            if "trading" not in self.supports:
                raise self._not_supported("trading")
            if not (self.live_enabled and get_settings().is_live_allowed):
                raise LiveTradingBlocked(
                    "Live trading is off: needs TRADING_MODE=live and the user's live mode"
                )
        return await self._place_order(req)

    async def _place_order(self, req: OrderRequest) -> OrderAck:
        raise self._not_supported("placing orders")

    async def modify_order(self, broker_order_id: str, changes: OrderChanges) -> OrderAck:
        raise self._not_supported("modifying orders")

    async def cancel_order(self, broker_order_id: str) -> None:
        raise self._not_supported("cancelling orders")

    async def order_status(self, broker_order_id: str) -> OrderStatus:
        raise self._not_supported("order status")

    async def positions(self) -> list[BrokerPosition]:
        raise self._not_supported("positions")

    async def funds(self) -> Funds:
        raise self._not_supported("funds")

    # ---- data

    async def instruments(self) -> list[Instrument]:
        raise self._not_supported("instrument list")

    async def historical(
        self, exchange: str, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Columns: ts (UTC, bar open), open, high, low, close (Decimal), volume (int)."""
        raise self._not_supported("historical data")

    def stream(self, instruments: list[tuple[str, str]]) -> AsyncIterator[Tick]:
        """Live ticks for [(exchange, symbol), ...]."""
        raise self._not_supported("live data stream")

    async def close(self) -> None:
        """Release network resources (HTTP clients, sockets)."""
