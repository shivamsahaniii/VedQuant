"""Build OHLCV candles from ticks.

Bars are aligned to NSE market time in IST: 1m/5m/15m on the clock (09:15 is aligned for
all three), 1h from 09:15, 1d one bar per date. A bar's `ts` is its open time in UTC.
Volume comes from the cumulative day volume in each tick (difference between ticks).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.brokers.base import TIMEFRAME_SECONDS, Tick

IST = ZoneInfo("Asia/Kolkata")
_SESSION_OPEN_MIN = 9 * 60 + 15


@dataclass(frozen=True)
class Bar:
    exchange: str
    symbol: str
    timeframe: str
    ts: datetime  # bar open, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    @property
    def end(self) -> datetime:
        if self.timeframe == "1d":
            return self.ts + timedelta(days=1)
        return self.ts + timedelta(seconds=TIMEFRAME_SECONDS[self.timeframe])

    def as_dict(self) -> dict[str, object]:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "ts": self.ts.isoformat(),
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": self.volume,
        }


def bar_start(ts: datetime, timeframe: str) -> datetime:
    """Open time (UTC) of the bar that contains `ts`."""
    local = ts.astimezone(IST)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    minute = local.hour * 60 + local.minute
    if timeframe == "1d":
        start_min = _SESSION_OPEN_MIN
    elif timeframe == "1h":
        start_min = _SESSION_OPEN_MIN + ((minute - _SESSION_OPEN_MIN) // 60) * 60
    else:
        size = TIMEFRAME_SECONDS[timeframe] // 60
        start_min = (minute // size) * size
    return (midnight + timedelta(minutes=start_min)).astimezone(UTC)


class CandleBuilder:
    def __init__(self, timeframes: tuple[str, ...] = ("1m", "5m")) -> None:
        for tf in timeframes:
            if tf not in TIMEFRAME_SECONDS:
                raise ValueError(f"Unknown timeframe {tf}")
        self.timeframes = timeframes
        self._bars: dict[tuple[str, str, str], Bar] = {}
        self._last_cum: dict[tuple[str, str], int] = {}

    def current(self, exchange: str, symbol: str, timeframe: str) -> Bar | None:
        """The bar still forming (not closed yet)."""
        return self._bars.get((exchange, symbol, timeframe))

    def on_tick(self, tick: Tick) -> list[Bar]:
        """Add a tick. Returns bars that closed because this tick started a new bar."""
        key = (tick.exchange, tick.symbol)
        prev = self._last_cum.get(key)
        if prev is not None and tick.volume >= prev:
            qty = tick.volume - prev
        else:  # first tick, or the day's counter reset
            qty = tick.last_qty
        if tick.volume:
            self._last_cum[key] = tick.volume

        closed: list[Bar] = []
        for tf in self.timeframes:
            bkey = (tick.exchange, tick.symbol, tf)
            start = bar_start(tick.ts, tf)
            bar = self._bars.get(bkey)
            if bar is not None and start < bar.ts:
                continue  # late, out-of-order tick for an already-closed bar: ignore
            if bar is not None and start > bar.ts:
                closed.append(bar)
                bar = None
            if bar is None:
                self._bars[bkey] = Bar(
                    tick.exchange,
                    tick.symbol,
                    tf,
                    start,
                    tick.ltp,
                    tick.ltp,
                    tick.ltp,
                    tick.ltp,
                    qty,
                )
            else:
                self._bars[bkey] = replace(
                    bar,
                    high=max(bar.high, tick.ltp),
                    low=min(bar.low, tick.ltp),
                    close=tick.ltp,
                    volume=bar.volume + qty,
                )
        return closed

    def flush(self, now: datetime) -> list[Bar]:
        """Close every bar whose time is over (call periodically: quiet symbols get no tick)."""
        closed = [b for b in self._bars.values() if b.end <= now]
        for b in closed:
            del self._bars[(b.exchange, b.symbol, b.timeframe)]
        return closed
