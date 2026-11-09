from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.brokers.base import Tick
from app.data.candles import IST, CandleBuilder, bar_start

D = Decimal
T0 = datetime(2026, 11, 9, 9, 15, 0, tzinfo=IST)


def tick(sec: float, price: str, cum: int, sym: str = "SBIN", last_qty: int = 0) -> Tick:
    return Tick("NSE", sym, T0 + timedelta(seconds=sec), D(price), cum, last_qty)


@pytest.mark.parametrize(
    "local, tf, expected",
    [
        ("09:15:00", "1m", "09:15"),
        ("09:16:59", "1m", "09:16"),
        ("09:19:59", "5m", "09:15"),
        ("09:20:00", "5m", "09:20"),
        ("09:29:00", "15m", "09:15"),
        ("10:14:59", "1h", "09:15"),
        ("10:15:00", "1h", "10:15"),
        ("15:29:59", "1d", "09:15"),
    ],
)
def test_bar_start_alignment(local: str, tf: str, expected: str) -> None:
    h, m, s = map(int, local.split(":"))
    ts = T0.replace(hour=h, minute=m, second=s)
    start = bar_start(ts, tf)
    assert start.tzinfo == UTC
    assert start.astimezone(IST).strftime("%H:%M") == expected


def test_ohlcv_and_close_on_next_bar() -> None:
    b = CandleBuilder(("1m",))
    assert b.on_tick(tick(0, "800", 1000, last_qty=1000)) == []
    b.on_tick(tick(10, "805", 1100))
    b.on_tick(tick(20, "798.5", 1150))
    b.on_tick(tick(59, "801", 1200))
    closed = b.on_tick(tick(61, "802", 1300))  # 09:16 starts -> 09:15 bar closes
    (bar,) = closed
    assert (bar.open, bar.high, bar.low, bar.close) == (D("800"), D("805"), D("798.5"), D("801"))
    assert bar.volume == 1000 + 100 + 50 + 50
    assert bar.ts == T0.astimezone(UTC)
    forming = b.current("NSE", "SBIN", "1m")
    assert forming is not None and forming.open == D("802") and forming.volume == 100


def test_1m_and_5m_together() -> None:
    b = CandleBuilder(("1m", "5m"))
    closed_all = []
    for i in range(0, 301, 30):  # 09:15:00 .. 09:20:00
        closed_all += b.on_tick(tick(i, str(800 + i / 30), 1000 + i))
    tfs = sorted(c.timeframe for c in closed_all)
    assert tfs.count("1m") == 5 and tfs.count("5m") == 1
    five = next(c for c in closed_all if c.timeframe == "5m")
    assert five.open == D("800") and five.close == D("809")  # last tick before 09:20


def test_symbols_are_independent() -> None:
    b = CandleBuilder(("1m",))
    b.on_tick(tick(0, "800", 10, "SBIN"))
    b.on_tick(tick(0, "1800", 10, "INFY"))
    closed = b.on_tick(tick(70, "801", 20, "SBIN"))
    assert [c.symbol for c in closed] == ["SBIN"]
    assert b.current("NSE", "INFY", "1m") is not None


def test_flush_closes_quiet_symbols() -> None:
    b = CandleBuilder(("1m",))
    b.on_tick(tick(5, "800", 10))
    assert b.flush(T0 + timedelta(seconds=59)) == []
    (bar,) = b.flush(T0 + timedelta(seconds=60))
    assert bar.close == D("800")
    assert b.current("NSE", "SBIN", "1m") is None


def test_late_tick_ignored() -> None:
    b = CandleBuilder(("1m",))
    b.on_tick(tick(65, "800", 10))
    assert b.on_tick(tick(30, "999", 20)) == []  # belongs to an older bar
    bar = b.current("NSE", "SBIN", "1m")
    assert bar is not None and bar.high == D("800")


def test_index_without_volume() -> None:
    b = CandleBuilder(("1m",))
    b.on_tick(Tick("NSE", "NIFTY50", T0, D("24000"), 0, 0))
    b.on_tick(Tick("NSE", "NIFTY50", T0 + timedelta(seconds=30), D("24010"), 0, 0))
    bar = b.current("NSE", "NIFTY50", "1m")
    assert bar is not None and bar.volume == 0 and bar.high == D("24010")


def test_unknown_timeframe() -> None:
    with pytest.raises(ValueError):
        CandleBuilder(("7m",))
