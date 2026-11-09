"""Which market data the feed runs: a user's real broker feed, or the simulator.

Rules (paper trading on REAL prices, decided 2026-11-09):
  * If a user has chosen a real broker (today: Dhan) as the data source for stocks or indices in
    Settings → Connections, and that broker account is connected, the feed streams REAL prices from
    that user's own key. The simulator is off.
  * The feed never falls back to simulated prices silently. If the token expires or the connection
    fails, the feed status says so and no candles are produced (so no trades), until it is fixed.
  * Only the data-source owner's strategies trade on that feed and only they see its prices
    (one user's broker data is not shared with other users).
  * With no real source chosen, the simulator runs as before (for testing at any time).

One live feed at a time for now; the first eligible user (admins first) owns it.
TODO: one feed per user with a real source (multi-user live data), see md/plans.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.catalog import BY_KEY as CONNECTORS
from app.engine.nse import IST, TradingCalendar
from app.models import BrokerAccount, PlatformSetting, Strategy, User, UserSetting, WatchItem

FEED_KEY = "vq:feed"  # str: current feed status JSON
FEED_CHANNEL = "vq:feed"  # channel: same JSON on every change
INDEX = ("NSE", "NIFTY50")  # always streamed: the market mood reads it
FEED_OPEN = time(9, 0)  # connect a little before 09:15 so the first candle is complete
FEED_CLOSE = time(15, 35)
MAX_SYMBOLS = 200


@dataclass(frozen=True)
class LiveSource:
    user_id: uuid.UUID
    account_id: uuid.UUID
    broker: str  # adapter key, e.g. "dhan"
    connector: str  # catalog key


@dataclass
class FeedStatus:
    source: str  # "simulator" | connector key
    state: str  # "live" | "connecting" | "closed" | "error" | "simulated"
    message: str = ""
    owner_user_id: str | None = None
    symbols: int = 0
    missing: list[str] = field(default_factory=list)
    since: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def is_real(self) -> bool:
        return self.source != "simulator"

    def as_json(self) -> str:
        return json.dumps(asdict(self))


def parse_status(raw: str | None) -> FeedStatus | None:
    if not raw:
        return None
    try:
        return FeedStatus(**json.loads(raw))
    except (TypeError, ValueError):
        return None


def can_see_feed(status: FeedStatus | None, user_id: uuid.UUID | str) -> bool:
    """A real feed is visible only to its owner; the simulator to everyone."""
    return status is None or not status.is_real or status.owner_user_id == str(user_id)


HOLIDAYS_KEY = "nse_holidays"  # platform setting: ["2026-11-10", ...] (from NSE's circular)


async def load_calendar(db: AsyncSession) -> TradingCalendar:
    """Exchange holidays from the platform setting `nse_holidays`. TODO(verify) each date against
    NSE's official holiday circular; an admin keeps the list current."""
    row = await db.get(PlatformSetting, HOLIDAYS_KEY)
    return TradingCalendar(row.value if row and isinstance(row.value, list) else [])


def in_feed_window(now: datetime, calendar: TradingCalendar | None = None) -> bool:
    t = now.astimezone(IST)
    cal = calendar or TradingCalendar()
    return cal.is_trading_day(t.date()) and FEED_OPEN <= t.time() < FEED_CLOSE


async def choose_source(db: AsyncSession) -> LiveSource | None:
    """First user (admins first) whose stocks/indices source is a connected real broker."""
    rows = (
        await db.execute(
            select(UserSetting, User)
            .join(User, User.id == UserSetting.user_id)
            .where(UserSetting.key == "connections", User.is_active.is_(True))
            .order_by((User.role == "admin").desc(), User.created_at)
        )
    ).all()
    for setting, user in rows:
        sources = (setting.value or {}).get("data_sources", {})
        for asset in ("indices", "stocks"):
            key = sources.get(asset)
            c = CONNECTORS.get(key or "")
            if not c or key == "paper" or not c.broker_key or c.status != "available":
                continue
            account = await db.scalar(
                select(BrokerAccount)
                .where(
                    BrokerAccount.user_id == user.id,
                    BrokerAccount.broker == c.broker_key,
                    BrokerAccount.status.in_(("connected", "expired", "error")),
                )
                .order_by(BrokerAccount.created_at)
            )
            if account is not None:
                return LiveSource(user.id, account.id, c.broker_key, c.key)
    return None


async def symbols_for(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, str]]:
    """What the owner needs: NIFTY 50 + their NSE/BSE Markets lists + their strategies' symbols."""
    out: list[tuple[str, str]] = [INDEX]
    items = (
        await db.scalars(
            select(WatchItem)
            .where(
                WatchItem.user_id == user_id,
                WatchItem.asset_class.in_(("indices", "stocks")),
                WatchItem.exchange.in_(("NSE", "BSE")),
            )
            .order_by(WatchItem.position)
        )
    ).all()
    out += [(w.exchange, w.symbol) for w in items]
    strategies = (
        await db.scalars(
            select(Strategy).where(Strategy.user_id == user_id, Strategy.status == "paper")
        )
    ).all()
    for s in strategies:
        out += [("NSE", sym) for sym in (s.params or {}).get("symbols") or []]
    seen: dict[tuple[str, str], None] = {}
    for key in out:
        seen.setdefault(key, None)
    return list(seen)[:MAX_SYMBOLS]


def status_payload(status: FeedStatus) -> dict[str, Any]:
    return asdict(status)
