"""NSE cash-market rules used by every agent: session clock, trading days, tick size.

Market times are IST; timestamps stored and passed around are UTC.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class Session:
    """Intraday clock. Defaults follow md/RISK.md; each user/strategy can tighten them."""

    open: time = time(9, 15)
    close: time = time(15, 30)
    no_entries_before: time = time(9, 30)  # let the opening range form first
    no_entries_after: time = time(14, 30)
    square_off: time = time(15, 15)  # before brokers' own auto square-off (~15:20)


SESSION = Session()


def ist(ts: datetime) -> datetime:
    return ts.astimezone(IST)


class TradingCalendar:
    """Weekdays minus exchange holidays.

    Holidays come from configuration (platform setting `nse_holidays`), not from code, because NSE
    publishes the list each year and can change it.
    TODO(verify): load NSE's official trading-holiday
    list (or the data broker's market-status endpoint) once a real data source is connected.
    """

    def __init__(self, holidays: Iterable[date | str] = ()):
        self.holidays = {d if isinstance(d, date) else date.fromisoformat(d) for d in holidays}

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def is_open(self, ts: datetime, session: Session = SESSION) -> bool:
        t = ist(ts)
        return self.is_trading_day(t.date()) and session.open <= t.time() < session.close


# NSE price-band tick sizes for equities, used only when the instrument master gives no tick size.
# TODO(verify): NSE revises these by circular; always prefer the instrument's own tick size
# (Dhan scrip master `SEM_TICK_SIZE`, stored in instruments.tick_size).
_TICK_BANDS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("250"), Decimal("0.01")),
    (Decimal("1000"), Decimal("0.05")),
    (Decimal("5000"), Decimal("0.10")),
    (Decimal("10000"), Decimal("0.50")),
    (Decimal("20000"), Decimal("1.00")),
)
_TOP_TICK = Decimal("5.00")


def tick_size(price: Decimal, instrument_tick: Decimal | None = None) -> Decimal:
    if instrument_tick and instrument_tick > 0:
        return instrument_tick
    for upper, tick in _TICK_BANDS:
        if price < upper:
            return tick
    return _TOP_TICK


def round_to_tick(price: Decimal, tick: Decimal, *, up: bool | None = None) -> Decimal:
    """Round onto the tick grid: up=True ceiling, up=False floor, None nearest."""
    rounding = ROUND_CEILING if up is True else ROUND_FLOOR if up is False else ROUND_HALF_UP
    return ((price / tick).quantize(Decimal(1), rounding=rounding) * tick).quantize(tick)


def to_dec(v: float | int | str | Decimal) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))
