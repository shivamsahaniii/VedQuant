from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.brokers.base import Tick
from app.data.candles import CandleBuilder
from app.data.simulator import INDEX, IST, MarketSimulator
from app.engine.context import breadth_of, compute_context, session_phase

T0 = datetime(2026, 11, 9, 9, 15, tzinfo=IST)


def candles(closes: list[float], spread: float = 3.0, step_min: int = 5) -> pd.DataFrame:
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        rows.append(
            {
                "ts": (T0 + timedelta(minutes=step_min * i)).astimezone(UTC),
                "open": prev,
                "high": max(prev, c) + spread,
                "low": min(prev, c) - spread,
                "close": c,
                "volume": 0.0,
            }
        )
        prev = c
    return pd.DataFrame(rows)


def stocks(up: int, down: int) -> dict[str, tuple[float, float]]:
    s = {f"U{i}": (100.0, 101.0) for i in range(up)}
    s.update({f"D{i}": (100.0, 99.0) for i in range(down)})
    return s


def test_clear_uptrend_is_bullish() -> None:
    df = candles([24000 + 15 * i for i in range(40)])
    ctx = compute_context(df, stocks(8, 2), T0 + timedelta(hours=3))
    assert (ctx.trend, ctx.strength, ctx.bias) == ("up", "strong", "bullish")
    assert not ctx.warming_up
    assert ctx.breadth.label == "broad up"
    assert ctx.summary.startswith("Uptrend · strong")
    assert any("above EMA20" in r for r in ctx.reasons)


def test_clear_downtrend_is_bearish() -> None:
    df = candles([24000 - 15 * i for i in range(40)])
    ctx = compute_context(df, stocks(1, 9), T0 + timedelta(hours=3))
    assert (ctx.trend, ctx.bias) == ("down", "bearish")
    assert "9/10 stocks falling" in ctx.summary


def test_choppy_market_is_sideways_and_not_strong() -> None:
    import random

    rng = random.Random(4)
    closes = [24000 + rng.gauss(0, 15) for _ in range(60)]  # random back-and-forth, no trend
    ctx = compute_context(candles(closes), stocks(5, 5), T0 + timedelta(hours=5))
    assert ctx.trend == "sideways" and ctx.strength != "strong" and ctx.bias == "neutral"


def test_uptrend_but_broad_selling_is_neutral() -> None:
    df = candles([24000 + 15 * i for i in range(40)])
    assert compute_context(df, stocks(1, 9), T0 + timedelta(hours=3)).bias == "neutral"


def test_volatility_levels() -> None:
    calm = compute_context(candles([24000.0] * 30, spread=2), {}, T0)
    wild = compute_context(candles([24000.0] * 30, spread=60), {}, T0)
    assert calm.volatility == "low" and wild.volatility == "high"


def test_warming_up_uses_day_move() -> None:
    df = candles([24000, 24030, 24060, 24090, 24120])
    ctx = compute_context(df, {}, T0 + timedelta(minutes=25))
    assert ctx.warming_up and ctx.trend == "up"
    assert "Warming up" in ctx.reasons[0]


def test_no_data() -> None:
    ctx = compute_context(
        pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"]), {}, T0
    )
    assert ctx.warming_up and ctx.summary == "Waiting for market data"


@pytest.mark.parametrize(
    "hhmm, phase",
    [
        ("09:00", "pre-open"),
        ("09:20", "opening"),
        ("12:00", "mid-day"),
        ("15:00", "closing"),
        ("16:00", "closed"),
    ],
)
def test_session_phase(hhmm: str, phase: str) -> None:
    h, m = map(int, hhmm.split(":"))
    assert session_phase(T0.replace(hour=h, minute=m)) == phase


def test_breadth_flat_band() -> None:
    b = breadth_of({"A": (100.0, 100.04), "B": (100.0, 100.5), "C": (100.0, 99.0)})
    assert (b.up, b.down, b.flat) == (1, 1, 1)


# ---------------------------------------------------------------- against the simulator


def simulated_context(seed: int, regime: str, until: str = "13:30") -> str:
    sim = MarketSimulator(seed=seed, day=date(2026, 11, 9), regime=regime)
    builder = CandleBuilder(("5m",))
    bars, opens, last = [], {}, {}
    h, m = map(int, until.split(":"))
    end = T0.replace(hour=h, minute=m)
    now = T0
    while now < end:
        for t in sim.step(now, 10):
            tick = Tick(t.exchange, t.symbol, t.ts, t.ltp, t.volume, t.last_qty)
            if (t.exchange, t.symbol) == INDEX:
                bars += builder.on_tick(tick)
            else:
                opens.setdefault(t.symbol, float(t.ltp))
                last[t.symbol] = float(t.ltp)
        now += timedelta(seconds=10)
    df = pd.DataFrame(
        [
            {
                "ts": b.ts,
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": 0.0,
            }
            for b in bars
        ]
    )
    stocks_ = {s: (opens[s], last[s]) for s in opens}
    return compute_context(df, stocks_, end).trend


@pytest.mark.parametrize("regime, expected", [("trend_up", "up"), ("trend_down", "down")])
def test_detects_simulated_trend_days(regime: str, expected: str) -> None:
    hits = sum(simulated_context(seed, regime) == expected for seed in range(10))
    assert hits >= 6, hits  # most trend days are recognised (a rule, not a crystal ball)


def test_sideways_days_rarely_called_trends() -> None:
    trends = [simulated_context(seed, "sideways") for seed in range(10)]
    assert trends.count("sideways") >= 5, trends
