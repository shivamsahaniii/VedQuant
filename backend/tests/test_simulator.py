import math
import statistics
from datetime import date, datetime, timedelta

import pytest

from app.data.simulator import (
    INDEX,
    IST,
    REGIMES,
    MarketSimulator,
    session_progress,
    to_tick,
    volume_shape,
)

DAY = date(2026, 11, 9)
OPEN = datetime(2026, 11, 9, 9, 15, tzinfo=IST)
STEP = 10  # seconds per step: a full session = 2250 steps


def run_session(sim: MarketSimulator) -> dict[tuple[str, str], list[float]]:
    series: dict[tuple[str, str], list[float]] = {}
    for i in range(22_500 // STEP):
        for t in sim.step(OPEN + timedelta(seconds=i * STEP), dt=STEP):
            series.setdefault((t.exchange, t.symbol), []).append(float(t.ltp))
    return series


def day_return(prices: list[float]) -> float:
    return prices[-1] / prices[0] - 1


@pytest.mark.parametrize("regime, sign", [("trend_up", 1), ("trend_down", -1)])
def test_trend_days_trend(regime: str, sign: int) -> None:
    wins = sum(
        1
        for seed in range(12)
        if sign * day_return(run_session(MarketSimulator(seed, DAY, regime))[INDEX]) > 0
    )
    assert wins >= 10  # direction is right on most days, not all (like real markets)


def test_volatile_days_swing_more_than_sideways() -> None:
    def avg_range(regime: str) -> float:
        ranges = []
        for seed in range(8):
            idx = run_session(MarketSimulator(seed, DAY, regime))[INDEX]
            ranges.append((max(idx) - min(idx)) / idx[0])
        return statistics.mean(ranges)

    assert avg_range("volatile") > 1.8 * avg_range("sideways")


def test_stocks_follow_the_index() -> None:
    s = run_session(MarketSimulator(3, DAY, "trend_up"))

    def returns(p: list[float]) -> list[float]:
        return [math.log(b / a) for a, b in zip(p, p[1:], strict=False)][::6]  # 1-min returns

    idx = returns(s[INDEX])
    for sym in ("SBIN", "HDFCBANK", "ICICIBANK"):  # high-beta banks
        corr = statistics.correlation(idx, returns(s[("NSE", sym)]))
        assert corr > 0.4, (sym, corr)


def test_same_seed_and_day_repeat_exactly() -> None:
    a = MarketSimulator(seed=5, day=DAY)
    b = MarketSimulator(seed=5, day=DAY)
    assert a.regime == b.regime
    for i in range(50):
        now = OPEN + timedelta(seconds=i)
        assert [t.ltp for t in a.step(now, 1)] == [t.ltp for t in b.step(now, 1)]


def test_regime_changes_with_day() -> None:
    regimes = {MarketSimulator(seed=1, day=DAY + timedelta(days=d)).regime for d in range(30)}
    assert regimes == set(REGIMES)


def test_ticks_are_valid() -> None:
    sim = MarketSimulator(seed=2, day=DAY)
    last_vol: dict[str, int] = {}
    for i in range(200):
        for t in sim.step(OPEN + timedelta(seconds=i), 1):
            assert t.ltp > 0 and t.ltp % to_tick(0.05) == 0
            if (t.exchange, t.symbol) != INDEX:
                assert t.volume > last_vol.get(t.symbol, 0) and t.last_qty >= 1
                last_vol[t.symbol] = t.volume
    assert len(last_vol) == 10


def test_unknown_regime_rejected() -> None:
    with pytest.raises(ValueError):
        MarketSimulator(seed=1, day=DAY, regime="moon")


def test_session_helpers() -> None:
    assert session_progress(OPEN) == 0
    assert session_progress(OPEN + timedelta(hours=8)) == 1
    assert volume_shape(0) > volume_shape(0.5) < volume_shape(1)
    avg = statistics.mean(volume_shape(i / 1000) for i in range(1001))
    assert 0.95 < avg < 1.05
