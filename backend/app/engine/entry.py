"""Entry Timer agent: is a scanner setup still a valid entry RIGHT NOW, in the real market?

A setup is found on a closed candle. Before it becomes an entry, the real-market checks:
  * the candle really closed (no half-built candles),
  * the data is fresh (a feed that lags makes a late entry, which is a different trade),
  * it is a trading day and inside the entry window (09:30-14:30 IST by default),
  * the market mood allowed it,
  * the live price has not already run away from the trigger (no chasing) and has not fallen back
    through the level (the breakout already failed),
  * one entry per setup per day (the trigger key doubles as the idempotent order_ref seed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

import pandas as pd

from app.engine.nse import SESSION, Session, TradingCalendar, ist, to_dec
from app.engine.setups import ScanHit

Status = Literal["go", "skip"]


@dataclass(frozen=True)
class EntryParams:
    timeframe_minutes: int = 5
    max_delay: timedelta = timedelta(seconds=90)  # after the candle closes
    max_chase_pct: Decimal = Decimal("0.30")  # live price may be at most this far past the close


@dataclass(frozen=True)
class EntryDecision:
    status: Status
    reason: str
    hit: ScanHit
    entry_price: Decimal | None = None
    candle_close_at: datetime | None = None
    valid_until: datetime | None = None
    trigger_key: str = ""


def trigger_key(hit: ScanHit) -> str:
    s = hit.setup
    day = ist(pd.Timestamp(s.bar_ts).to_pydatetime()).date().isoformat()
    return f"{s.rule}:{s.symbol}:{s.side}:{day}"


def decide_entry(
    hit: ScanHit,
    now: datetime,
    ltp: Decimal | None,
    *,
    already_triggered: set[str] | frozenset[str] = frozenset(),
    params: EntryParams | None = None,
    calendar: TradingCalendar | None = None,
    session: Session = SESSION,
) -> EntryDecision:
    p = params or EntryParams()
    cal = calendar or TradingCalendar()
    s = hit.setup
    key = trigger_key(hit)
    closed_at = pd.Timestamp(s.bar_ts).to_pydatetime() + timedelta(minutes=p.timeframe_minutes)
    valid_until = closed_at + p.max_delay

    def skip(reason: str) -> EntryDecision:
        return EntryDecision("skip", reason, hit, None, closed_at, valid_until, key)

    if now < closed_at:
        return skip("Candle has not closed yet")
    if key in already_triggered:
        return skip("Already entered this setup today")
    if not hit.mood.ok:
        return skip(f"Market mood: {hit.mood.reason}")
    t = ist(closed_at)
    if not cal.is_trading_day(t.date()):
        return skip("Not a trading day")
    if t.time() < session.no_entries_before:
        return skip(f"Before the entry window ({session.no_entries_before:%H:%M} IST)")
    if t.time() > session.no_entries_after:
        return skip(f"After the entry window ({session.no_entries_after:%H:%M} IST)")
    if now > valid_until:
        late = int((now - closed_at).total_seconds())
        return skip(f"Too late: {late}s after the candle closed (data or engine lagging)")
    if ltp is None:
        return skip("No live price")

    close = to_dec(s.price)
    level = to_dec(s.level) if s.level is not None else None
    sign = 1 if s.side == "buy" else -1
    moved_pct = (ltp - close) / close * 100 * sign
    if moved_pct > p.max_chase_pct:
        return skip(f"Price already ran {moved_pct:.2f}% past the trigger (max {p.max_chase_pct}%)")
    if level is not None and (ltp - level) * sign <= 0:
        return skip(f"Price is back through the level {level}: the move already failed")
    return EntryDecision(
        "go",
        f"{hit.rule_name} {s.side} confirmed at {ltp} ({hit.mood.reason})",
        hit,
        ltp,
        closed_at,
        valid_until,
        key,
    )
