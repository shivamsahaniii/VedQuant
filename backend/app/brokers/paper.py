"""Paper broker: simulated orders, positions, funds and a demo price feed.

Needs no API keys. Used for paper trading, tests, and the demo feed when a user has not
added a data key yet. All prices shown by its demo feed are synthetic.

Fill rules:
- MARKET: fills at the last price plus slippage (BUY pays more, SELL gets less).
- LIMIT: fills at the last price once it is at or better than the limit.
- SL-M: waits for the trigger (BUY: price >= trigger, SELL: price <= trigger), then MARKET.
- SL: waits for the trigger, then becomes a LIMIT at `price`.
- Orders with no known price yet stay open and are checked on every new price.
- Margin: full notional (no leverage). An order that would increase exposure beyond equity
  is rejected at fill time.
"""

from __future__ import annotations

import asyncio
import random
import uuid
import zlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import ClassVar
from zoneinfo import ZoneInfo

import pandas as pd

from app.brokers.base import (
    TIMEFRAME_SECONDS,
    BrokerAdapter,
    BrokerCredentials,
    BrokerPosition,
    Capability,
    ConnectionReport,
    FieldSpec,
    Funds,
    Instrument,
    OrderAck,
    OrderChanges,
    OrderRejected,
    OrderRequest,
    OrderState,
    OrderStatus,
    Product,
    Purpose,
    Tick,
    Timeframe,
)
from app.data.simulator import SIM_INDEX, SIM_STOCKS, MarketSimulator, SimInstrument

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
TICK_SIZE = Decimal("0.05")

# Demo universe. Base prices are illustrative only, not real quotes.
DEMO_INSTRUMENTS: list[tuple[str, str, Decimal]] = [
    ("RELIANCE", "Reliance Industries", Decimal("2900")),
    ("TCS", "Tata Consultancy Services", Decimal("4100")),
    ("INFY", "Infosys", Decimal("1800")),
    ("HDFCBANK", "HDFC Bank", Decimal("1700")),
    ("ICICIBANK", "ICICI Bank", Decimal("1250")),
    ("SBIN", "State Bank of India", Decimal("820")),
    ("ITC", "ITC", Decimal("470")),
    ("LT", "Larsen & Toubro", Decimal("3600")),
    ("AXISBANK", "Axis Bank", Decimal("1150")),
    ("KOTAKBANK", "Kotak Mahindra Bank", Decimal("1800")),
]
_BASE_PRICE = {sym: px for sym, _, px in DEMO_INSTRUMENTS}
_DEFAULT_BASE = Decimal("500")


def round_to_tick(price: Decimal, tick: Decimal = TICK_SIZE, *, up: bool | None = None) -> Decimal:
    """Round to the tick grid: up=True ceiling, up=False floor, None nearest."""
    rounding = ROUND_CEILING if up is True else ROUND_FLOOR if up is False else ROUND_HALF_UP
    return ((price / tick).quantize(Decimal(1), rounding=rounding) * tick).quantize(tick)


@dataclass
class _Order:
    req: OrderRequest
    broker_order_id: str
    status: OrderState
    triggered: bool = False
    filled_qty: int = 0
    avg_price: Decimal | None = None
    message: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True)
class _Pos:
    qty: int = 0
    avg: Decimal = Decimal(0)
    realised: Decimal = Decimal(0)


def apply_fill(pos: _Pos, signed_qty: int, price: Decimal) -> _Pos:
    """New position after a fill. Realised P&L is booked on the closed part."""
    if pos.qty == 0 or (pos.qty > 0) == (signed_qty > 0):
        total = abs(pos.qty) + abs(signed_qty)
        avg = (abs(pos.qty) * pos.avg + abs(signed_qty) * price) / total
        return _Pos(pos.qty + signed_qty, avg, pos.realised)
    closing = min(abs(pos.qty), abs(signed_qty))
    direction = 1 if pos.qty > 0 else -1
    realised = pos.realised + closing * (price - pos.avg) * direction
    new_qty = pos.qty + signed_qty
    if new_qty == 0:
        return _Pos(0, Decimal(0), realised)
    if (new_qty > 0) != (pos.qty > 0):  # flipped side: remainder opened at fill price
        return _Pos(new_qty, price, realised)
    return _Pos(new_qty, pos.avg, realised)


class PaperBroker(BrokerAdapter):
    key: ClassVar[str] = "paper"
    display_name: ClassVar[str] = "Paper trading (simulated)"
    supports: ClassVar[frozenset[Capability]] = frozenset({"trading", "data", "historical"})
    credential_fields: ClassVar[dict[Purpose, list[FieldSpec]]] = {"trading": [], "data": []}
    auth_type = "none"
    is_paper = True

    def __init__(
        self,
        credentials: BrokerCredentials | None = None,
        *,
        live_enabled: bool = False,
        starting_cash: Decimal = Decimal("100000"),
        slippage_bps: Decimal = Decimal("5"),
        seed: int | None = None,
        tick_interval: float = 1.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(credentials, live_enabled=live_enabled)
        self.starting_cash = starting_cash
        self.slippage_bps = slippage_bps
        self.tick_interval = tick_interval
        self._clock = clock or (lambda: datetime.now(UTC))
        self.seed = seed
        self.regime: str | None = None
        self._prices: dict[tuple[str, str], Decimal] = {}
        self._orders: dict[str, _Order] = {}
        self._by_ref: dict[uuid.UUID, str] = {}
        self._positions: dict[tuple[str, str, Product], _Pos] = {}
        self._seq = 0

    # ------------------------------------------------------------ prices

    def last_price(self, exchange: str, symbol: str) -> Decimal | None:
        return self._prices.get((exchange, symbol))

    def set_price(self, exchange: str, symbol: str, price: Decimal) -> None:
        """Feed a new price (from the demo stream, a real data feed, or a test)."""
        self._prices[(exchange, symbol)] = price
        for order in list(self._orders.values()):
            if order.req.exchange == exchange and order.req.symbol == symbol:
                self._try_fill(order)

    def on_tick(self, tick: Tick) -> None:
        self.set_price(tick.exchange, tick.symbol, tick.ltp)

    # ------------------------------------------------------------ auth

    async def test_connection(self) -> ConnectionReport:
        return ConnectionReport(
            ok=True,
            message="Paper broker ready (simulated, no real money)",
            purpose_ok={"trading": True, "data": True},
            funds=await self.funds(),
        )

    # ------------------------------------------------------------ trading

    async def _place_order(self, req: OrderRequest) -> OrderAck:
        existing = self._by_ref.get(req.order_ref)
        if existing is not None:  # idempotent retry
            o = self._orders[existing]
            return OrderAck(req.order_ref, o.broker_order_id, o.status, "duplicate order_ref")

        self._seq += 1
        boid = f"PAPER-{self._seq:06d}"
        status: OrderState = "TRIGGER_PENDING" if req.order_type in ("SL", "SL-M") else "OPEN"
        order = _Order(req=req, broker_order_id=boid, status=status, updated_at=self._clock())
        self._orders[boid] = order
        self._by_ref[req.order_ref] = boid
        self._try_fill(order)
        return OrderAck(req.order_ref, boid, order.status, order.message)

    async def modify_order(self, broker_order_id: str, changes: OrderChanges) -> OrderAck:
        order = self._get(broker_order_id)
        if order.status not in ("OPEN", "TRIGGER_PENDING"):
            raise OrderRejected(f"Cannot modify a {order.status} order")
        updates = {k: v for k, v in vars(changes).items() if v is not None}
        try:
            new_req = replace(order.req, **updates)
        except (ValueError, TypeError) as exc:
            raise OrderRejected(str(exc)) from None
        order.req = new_req
        if new_req.order_type in ("MARKET", "LIMIT"):
            order.status = "OPEN"
        order.updated_at = self._clock()
        self._try_fill(order)
        return OrderAck(new_req.order_ref, broker_order_id, order.status, order.message)

    async def cancel_order(self, broker_order_id: str) -> None:
        order = self._get(broker_order_id)
        if order.status not in ("OPEN", "TRIGGER_PENDING"):
            raise OrderRejected(f"Cannot cancel a {order.status} order")
        order.status = "CANCELLED"
        order.updated_at = self._clock()

    async def order_status(self, broker_order_id: str) -> OrderStatus:
        o = self._get(broker_order_id)
        return OrderStatus(
            order_ref=o.req.order_ref,
            broker_order_id=o.broker_order_id,
            status=o.status,
            exchange=o.req.exchange,
            symbol=o.req.symbol,
            side=o.req.side,
            qty=o.req.qty,
            filled_qty=o.filled_qty,
            avg_price=o.avg_price,
            message=o.message,
            updated_at=o.updated_at,
        )

    async def positions(self) -> list[BrokerPosition]:
        out = []
        for (exchange, symbol, product), p in self._positions.items():
            ltp = self.last_price(exchange, symbol)
            unrealised = (ltp - p.avg) * p.qty if (ltp is not None and p.qty) else Decimal(0)
            out.append(
                BrokerPosition(
                    exchange=exchange,
                    symbol=symbol,
                    product=product,
                    qty=p.qty,
                    avg_price=p.avg,
                    ltp=ltp,
                    realised_pnl=p.realised,
                    unrealised_pnl=unrealised,
                )
            )
        return out

    async def funds(self) -> Funds:
        equity = self._equity(self._positions)
        used = self._blocked(self._positions)
        unrealised = sum((p.unrealised_pnl for p in await self.positions()), Decimal(0))
        return Funds(available=equity - used, used_margin=used, total=equity + unrealised)

    # ------------------------------------------------------------ data

    async def instruments(self) -> list[Instrument]:
        stocks = [
            Instrument(
                broker=self.key,
                exchange="NSE",
                segment="EQ",
                symbol=sym,
                broker_token=f"DEMO-{sym}",
                name=f"{name} (demo)",
            )
            for sym, name, _ in DEMO_INSTRUMENTS
        ]
        index = Instrument(
            broker=self.key,
            exchange=SIM_INDEX.exchange,
            segment="IDX",
            symbol=SIM_INDEX.symbol,
            broker_token=f"DEMO-{SIM_INDEX.symbol}",
            name=SIM_INDEX.name,
        )
        return [index, *stocks]

    def simulator_for(self, instruments: list[tuple[str, str]]) -> MarketSimulator:
        """Market simulator covering `instruments` (unknown symbols get default behaviour)."""
        known = {(s.exchange, s.symbol): s for s in SIM_STOCKS}
        stocks = tuple(
            known.get(
                key,
                SimInstrument(key[0], key[1], key[1], float(_DEFAULT_BASE), 1.0, 0.01, 5000),
            )
            for key in instruments
            if key != (SIM_INDEX.exchange, SIM_INDEX.symbol)
        )
        return MarketSimulator(
            seed=self.seed, day=self._clock().astimezone(IST).date(), stocks=stocks
        )

    async def stream(self, instruments: list[tuple[str, str]]) -> AsyncIterator[Tick]:  # type: ignore[override]
        """Endless simulated market ticks (index + stocks), one round per `tick_interval` s."""
        sim = self.simulator_for(instruments)
        self.regime = sim.regime
        wanted = set(instruments)
        while True:
            for t in sim.step(self._clock(), dt=self.tick_interval or 1.0):
                if (t.exchange, t.symbol) not in wanted:
                    continue
                tick = Tick(t.exchange, t.symbol, t.ts, t.ltp, t.volume, t.last_qty)
                self.on_tick(tick)
                yield tick
            await asyncio.sleep(self.tick_interval)

    async def historical(
        self, exchange: str, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Deterministic synthetic candles for market hours on weekdays in [start, end)."""
        rng = random.Random(zlib.crc32(f"{exchange}:{symbol}:{timeframe}".encode()))  # noqa: S311
        price = _BASE_PRICE.get(symbol, _DEFAULT_BASE)
        rows = []
        for ts in _bar_times(timeframe, start, end):
            open_ = price
            closes = [open_]
            for _ in range(4):
                closes.append(max(TICK_SIZE, closes[-1] * (1 + Decimal(str(rng.gauss(0, 0.002))))))
            close = round_to_tick(closes[-1])
            high = round_to_tick(max(closes), up=True)
            low = round_to_tick(min(closes), up=False)
            rows.append(
                {
                    "ts": ts,
                    "open": round_to_tick(open_),
                    "high": max(high, round_to_tick(open_), close),
                    "low": min(low, round_to_tick(open_), close),
                    "close": close,
                    "volume": rng.randint(1_000, 100_000),
                }
            )
            price = close
        return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])

    # ------------------------------------------------------------ internals

    def _get(self, broker_order_id: str) -> _Order:
        try:
            return self._orders[broker_order_id]
        except KeyError:
            raise OrderRejected(f"Unknown order {broker_order_id}") from None

    def _equity(self, positions: dict[tuple[str, str, Product], _Pos]) -> Decimal:
        return self.starting_cash + sum((p.realised for p in positions.values()), Decimal(0))

    @staticmethod
    def _blocked(positions: dict[tuple[str, str, Product], _Pos]) -> Decimal:
        return sum((abs(p.qty) * p.avg for p in positions.values()), Decimal(0))

    def _try_fill(self, order: _Order) -> None:
        if order.status not in ("OPEN", "TRIGGER_PENDING"):
            return
        req = order.req
        ltp = self.last_price(req.exchange, req.symbol)
        if ltp is None:
            return

        if req.order_type in ("SL", "SL-M") and not order.triggered:
            if req.trigger_price is None:  # prevented by OrderRequest validation
                return
            hit = ltp >= req.trigger_price if req.side == "BUY" else ltp <= req.trigger_price
            if not hit:
                return
            order.triggered = True
            order.status = "OPEN"

        if req.order_type in ("MARKET", "SL-M"):
            factor = self.slippage_bps / Decimal(10_000)
            if req.side == "BUY":
                price = round_to_tick(ltp * (1 + factor), up=True)
            else:
                price = round_to_tick(ltp * (1 - factor), up=False)
        else:  # LIMIT, or SL after trigger
            if req.price is None:  # prevented by OrderRequest validation
                return
            marketable = ltp <= req.price if req.side == "BUY" else ltp >= req.price
            if not marketable:
                return
            price = ltp
        self._fill(order, price)

    def _fill(self, order: _Order, price: Decimal) -> None:
        req = order.req
        key = (req.exchange, req.symbol, req.product)
        old = self._positions.get(key, _Pos())
        signed = req.qty if req.side == "BUY" else -req.qty
        new = apply_fill(old, signed, price)

        after = {**self._positions, key: new}
        if abs(new.qty) > abs(old.qty) and self._blocked(after) > self._equity(after):
            order.status = "REJECTED"
            order.message = "Insufficient funds"
            order.updated_at = self._clock()
            return

        self._positions[key] = new
        order.status = "FILLED"
        order.filled_qty = req.qty
        order.avg_price = price
        order.updated_at = self._clock()


def _bar_times(timeframe: Timeframe, start: datetime, end: datetime) -> list[datetime]:
    """Bar open times (UTC) inside NSE market hours on weekdays, within [start, end)."""
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    out: list[datetime] = []
    day: date = start.astimezone(IST).date()
    last_day: date = end.astimezone(IST).date()
    while day <= last_day:
        if day.weekday() < 5:
            t = datetime.combine(day, MARKET_OPEN, IST)
            close = datetime.combine(day, MARKET_CLOSE, IST)
            if timeframe == "1d":
                if start <= t < end:
                    out.append(t.astimezone(UTC))
            else:
                while t < close:
                    if start <= t < end:
                        out.append(t.astimezone(UTC))
                    t += step
        day += timedelta(days=1)
    return out
