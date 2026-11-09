"""Scanner agent: each rule on hand-made candles, the market-mood filter, and no look-ahead."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engine import indicators as ind
from app.engine.setups import RULES, mood_check, scan
from app.strategies.catalog import TEMPLATES

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 10)  # a Tuesday


def candles(
    closes, day=DAY, start=(9, 15), minutes=5, spread=0.5, volumes=None, highs=None, lows=None
):
    """5-minute candles from a list of closes; open = previous close."""
    t0 = datetime(day.year, day.month, day.day, *start, tzinfo=IST).astimezone(UTC)
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        rows.append(
            {
                "ts": pd.Timestamp(t0 + timedelta(minutes=minutes * i)),
                "open": o,
                "high": highs[i] if highs else max(o, c) + spread,
                "low": lows[i] if lows else min(o, c) - spread,
                "close": c,
                "volume": volumes[i] if volumes else 1000,
            }
        )
        prev = c
    return pd.DataFrame(rows)


@dataclass
class Ctx:
    trend: str = "up"
    strength: str = "moderate"
    volatility: str = "normal"
    bias: str = "bullish"


def test_every_template_has_a_rule():
    assert set(RULES) == set(TEMPLATES)


# ---------------------------------------------------------------- indicators


def test_rsi_extremes_and_range():
    up = pd.Series(np.arange(1, 40, dtype=float))
    assert ind.rsi(up).iloc[-1] == 100
    assert ind.rsi(up[::-1].reset_index(drop=True)).iloc[-1] == 0
    noise = pd.Series(100 + np.random.default_rng(1).normal(0, 1, 300).cumsum())
    r = ind.rsi(noise).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    assert ind.rsi(up).iloc[:13].isna().all()


def test_supertrend_follows_the_trend_and_flips():
    closes = list(np.linspace(100, 130, 40)) + list(np.linspace(129, 95, 40))
    st = ind.supertrend(candles(closes))
    assert st["direction"].iloc[39] == 1
    assert st["direction"].iloc[-1] == -1
    # line sits under price in an uptrend, over it in a downtrend
    assert st["line"].iloc[39] < closes[39]
    assert st["line"].iloc[-1] > closes[-1]


@pytest.mark.parametrize(
    "fn",
    [
        lambda df: ind.rsi(df["close"]),
        lambda df: ind.supertrend(df)["line"],
        lambda df: ind.ema(df["close"], 9),
        lambda df: ind.vwap(df, pd.Series([0] * len(df))),
    ],
)
def test_indicators_have_no_look_ahead(fn):
    rng = np.random.default_rng(7)
    df = candles(
        list(100 + rng.normal(0, 1, 120).cumsum()), volumes=list(rng.integers(500, 5000, 120))
    )
    full = fn(df)
    for i in (30, 60, 119):
        part = fn(df.iloc[: i + 1])
        assert np.isclose(full.iloc[i], part.iloc[-1], equal_nan=True)


def test_scanner_replay_matches_bar_by_bar():
    """Scanning a day candle by candle never depends on candles that had not closed yet."""
    rng = np.random.default_rng(3)
    df = candles(
        list(1000 + rng.normal(0, 3, 75).cumsum()), volumes=list(rng.integers(500, 9000, 75))
    )
    ctx = Ctx()
    seen = [h.as_dict() for i in range(1, len(df) + 1) for h in scan("X", df.iloc[:i], ctx)]
    again = [h.as_dict() for i in range(1, len(df) + 1) for h in scan("X", df.iloc[:i].copy(), ctx)]
    assert seen == again
    for h in seen:  # every hit is stamped with the candle it was found on, never a later one
        assert pd.Timestamp(h["bar_ts"]) <= df["ts"].iloc[-1]


# ---------------------------------------------------------------- ORB

# 09:15, 09:20, 09:25 = the opening range (high 101.5, low 98.5 with spread 0.5)
OR = [100, 101, 99]


def test_orb_buy_on_first_close_above_range():
    df = candles(OR + [100.5, 102.2])
    s = RULES["orb"].detect(df, "SBIN")
    assert s.side == "buy" and s.level == 101.5 and s.price == 102.2
    assert s.data == {"or_high": 101.5, "or_low": 98.5, "or_bars": 3}
    assert "opening range high" in s.reason


def test_orb_only_the_first_breakout_counts():
    assert RULES["orb"].detect(candles(OR + [102.2, 103]), "SBIN") is None


def test_orb_wick_above_is_not_a_breakout():
    closes = OR + [101.4]
    highs = [100.5, 101.5, 101.5, 103.0]
    assert RULES["orb"].detect(candles(closes, highs=highs), "SBIN") is None


def test_orb_sell_below_range_and_nothing_during_the_range():
    s = RULES["orb"].detect(candles(OR + [98.0]), "SBIN")
    assert s.side == "sell" and s.level == 98.5
    assert RULES["orb"].detect(candles(OR[:2]), "SBIN") is None


def test_orb_uses_only_todays_range():
    yday = candles([200, 210, 190, 205], day=DAY - timedelta(days=1))
    df = pd.concat([yday, candles(OR + [102.2])], ignore_index=True)
    assert RULES["orb"].detect(df, "SBIN").data["or_high"] == 101.5


# ---------------------------------------------------------------- the other rules


def test_vwap_cross_needs_volume():
    closes = [100, 99, 98, 97, 98, 102]
    low_vol = candles(closes, volumes=[1000] * 6)
    assert RULES["vwap_cross"].detect(low_vol, "TCS") is None
    s = RULES["vwap_cross"].detect(candles(closes, volumes=[1000] * 5 + [3000]), "TCS")
    assert s.side == "buy" and "VWAP" in s.reason and "3.0x" in s.reason


def test_volume_rules_need_enough_history():
    # a "surge" against one earlier candle proves nothing
    df = candles([100, 99, 102], volumes=[1000, 1000, 5000])
    assert RULES["vwap_cross"].detect(df, "TCS") is None


def test_supertrend_flip_signal():
    closes = list(np.linspace(130, 100, 40)) + list(np.linspace(101, 125, 25))
    df = candles(closes)
    hits = [RULES["supertrend"].detect(df.iloc[:i], "INFY") for i in range(2, len(df) + 1)]
    sides = [h.side for h in hits if h]
    assert sides and sides[-1] == "buy"


def test_ema_cross_signal():
    closes = list(np.linspace(120, 100, 30)) + [101, 103, 106, 110, 115, 120]
    df = candles(closes)
    hits = [RULES["ema_cross"].detect(df.iloc[:i], "HDFC") for i in range(2, len(df) + 1)]
    assert [h.side for h in hits if h] == ["buy"]


def test_rsi_reversal_signal():
    closes = list(np.linspace(100, 80, 20)) + [81, 82.5, 84, 86, 88]
    df = candles(closes)
    hits = [RULES["rsi_reversal"].detect(df.iloc[:i], "ITC") for i in range(2, len(df) + 1)]
    found = [h for h in hits if h]
    assert found and found[0].side == "buy" and "oversold" in found[0].reason


def test_breakout_volume_signal():
    closes = [100 + (i % 3) for i in range(20)] + [106]
    assert RULES["breakout_volume"].detect(candles(closes), "LT") is None  # no volume surge
    s = RULES["breakout_volume"].detect(candles(closes, volumes=[1000] * 20 + [2000]), "LT")
    assert s.side == "buy" and s.level == 102.5


# ---------------------------------------------------------------- market mood filter


def test_trend_rules_go_with_the_market():
    assert RULES["orb"].mood_check("buy", Ctx()).ok
    no = RULES["orb"].mood_check("buy", Ctx(trend="down", bias="bearish"))
    assert not no.ok and "downtrend" in no.reason
    assert not RULES["vwap_cross"].mood_check("buy", Ctx(trend="sideways", bias="bearish")).ok
    assert RULES["supertrend"].mood_check("sell", Ctx(trend="down", bias="bearish")).ok


def test_orb_skips_weak_sideways_days():
    m = RULES["orb"].mood_check("buy", Ctx(trend="sideways", strength="weak", bias="neutral"))
    assert not m.ok and "Sideways" in m.reason
    assert (
        RULES["breakout_volume"]
        .mood_check("buy", Ctx(trend="sideways", strength="weak", bias="neutral"))
        .ok
    )


def test_reversion_avoids_strong_trends():
    rule = RULES["rsi_reversal"]
    assert not rule.mood_check("buy", Ctx(trend="down", strength="strong", bias="bearish")).ok
    assert rule.mood_check("buy", Ctx(trend="sideways", strength="weak", bias="neutral")).ok
    assert rule.mood_check("buy", Ctx(trend="down", strength="moderate", bias="bearish")).ok


def test_no_mood_yet():
    assert not mood_check("orb", "breakout", "buy", None).ok


def test_scan_reports_mood_with_each_hit():
    hits = scan("SBIN", candles(OR + [102.2]), Ctx(trend="down", bias="bearish"), {"orb": None})
    assert len(hits) == 1
    d = hits[0].as_dict()
    assert d["rule_name"] == "Opening Range Breakout" and d["mood_ok"] is False
