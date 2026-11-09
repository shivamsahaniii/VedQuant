import numpy as np
import pandas as pd
import pytest

from app.engine.indicators import adx, atr, ema, slope, vwap


def frame(closes: list[float], spread: float = 1.0, volume: float = 100) -> pd.DataFrame:
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": c.shift(1).fillna(c.iloc[0]),
            "high": c + spread,
            "low": c - spread,
            "close": c,
            "volume": volume,
        }
    )


def test_ema_matches_hand_calculation() -> None:
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    e = ema(s, 3)
    assert np.isnan(e.iloc[1])
    # adjust=False: e0=1, k=0.5 -> 1.5, 2.25, 3.125, 4.0625
    assert e.iloc[4] == pytest.approx(4.0625)


def test_atr_constant_range() -> None:
    df = frame([100.0] * 30, spread=2.0)
    assert atr(df, 14).iloc[-1] == pytest.approx(4.0)


def test_adx_strong_on_trend_weak_on_chop() -> None:
    trend = frame([100 + i for i in range(60)])
    chop = frame([100 + (1 if i % 2 else -1) for i in range(60)])
    assert adx(trend).iloc[-1] > 40
    assert adx(chop).iloc[-1] < 20


def test_vwap_volume_weighted_and_resets_daily() -> None:
    df = pd.DataFrame(
        {
            "open": [10, 20, 30],
            "high": [10, 20, 30],
            "low": [10, 20, 30],
            "close": [10, 20, 30],
            "volume": [1, 3, 5],
        },
        dtype=float,
    )
    day = pd.Series(["d1", "d1", "d2"])
    v = vwap(df, day)
    assert v.iloc[1] == pytest.approx((10 * 1 + 20 * 3) / 4)
    assert v.iloc[2] == pytest.approx(30)  # new day restarts


def test_vwap_without_volume_is_plain_average() -> None:
    df = frame([10, 20, 30], spread=0, volume=0)
    assert vwap(df, pd.Series([1, 1, 1])).iloc[-1] == pytest.approx(20)


def test_no_look_ahead() -> None:
    """Values up to row i must not change when later rows are added."""
    rng = np.random.default_rng(1)
    closes = list(100 + rng.normal(0, 1, 80).cumsum())
    full, part = frame(closes), frame(closes[:50])
    for fn in (lambda d: ema(d["close"], 20), atr, adx):
        pd.testing.assert_series_equal(fn(full).iloc[:50], fn(part), check_names=False)


def test_slope() -> None:
    assert slope(pd.Series([100, 101, 102, 103, 104, 110.0]), 5).iloc[-1] == pytest.approx(0.10)


def test_adx_zero_when_no_directional_movement() -> None:
    flat = pd.DataFrame(
        {
            "open": [100.0] * 40,
            "high": [101.0] * 40,
            "low": [99.0] * 40,
            "close": [100.0] * 40,
            "volume": [1.0] * 40,
        }
    )
    assert adx(flat).iloc[-1] == pytest.approx(0.0)
