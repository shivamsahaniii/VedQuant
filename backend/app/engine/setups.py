"""Scanner agent rules: find trade setups on CLOSED candles.

One rule per strategy template (app/strategies/catalog.py). Each rule:
  * `detect(df)` looks at the LAST row of `df` (the candle that just closed) and the rows before it,
    and returns a Setup or None. It never sees a later row, so there is no look-ahead.
  * `mood_check(side, ctx)` says whether today's market mood suits the rule, with the reason.

A setup is "matched a rule", not "a buy". Entry timing, stop/target, odds, risk and the paper broker
are the next agents in the chain (md/plans/paper-trading-engine.md, A.3-A.7).

`df` columns: ts (UTC, candle START time), open, high, low, close, volume. Index rows (NIFTY) have
volume 0; volume checks are skipped for them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import time
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.engine import indicators as ind

IST = ZoneInfo("Asia/Kolkata")
Side = Literal["buy", "sell"]
Style = Literal["trend", "breakout", "reversion"]

OR_START, OR_END = time(9, 15), time(9, 30)  # NSE opening range: the first 15 minutes
MIN_VOLUME_BARS = 5  # a volume surge needs at least this many earlier candles to compare with


class Mood(Protocol):
    """What the rules need from the market context (app.engine.context.MarketContext)."""

    trend: str
    strength: str
    volatility: str
    bias: str


@dataclass(frozen=True)
class Setup:
    rule: str
    symbol: str
    side: Side
    bar_ts: pd.Timestamp  # start of the candle that triggered (UTC)
    price: float  # that candle's close
    level: float | None  # the level it crossed
    reason: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MoodCheck:
    ok: bool
    reason: str


@dataclass(frozen=True)
class Rule:
    key: str
    name: str
    style: Style
    detect_fn: Callable[[pd.DataFrame, str, dict[str, Any]], Setup | None]
    defaults: dict[str, Any]

    def detect(self, df: pd.DataFrame, symbol: str, params: dict[str, Any] | None = None):
        if df.empty:
            return None
        return self.detect_fn(
            df.reset_index(drop=True), symbol, {**self.defaults, **(params or {})}
        )

    def mood_check(self, side: Side, ctx: Mood | None) -> MoodCheck:
        return mood_check(self.key, self.style, side, ctx)


# ---------------------------------------------------------------- helpers


def ist_dates(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df["ts"], utc=True).dt.tz_convert(IST).dt.date


def today_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows from the same IST trading day as the last row."""
    days = ist_dates(df)
    return df[days == days.iloc[-1]]


def _ist_time(ts: Any) -> time:
    return pd.Timestamp(ts).tz_convert(IST).time()


def _crossed(prev_a: float, prev_b: float, a: float, b: float) -> int:
    """+1 when a crossed above b on the last row, -1 when below, 0 otherwise."""
    if any(np.isnan(x) for x in (prev_a, prev_b, a, b)):
        return 0
    if prev_a <= prev_b and a > b:
        return 1
    if prev_a >= prev_b and a < b:
        return -1
    return 0


def _volume_ok(df: pd.DataFrame, mult: float, lookback: int) -> tuple[bool, str]:
    """Last candle's volume vs the average of the `lookback` candles before it."""
    vol = df["volume"].astype(float)
    last = vol.iloc[-1]
    prior = vol.iloc[-lookback - 1 : -1]
    if (prior <= 0).all() and last <= 0:
        return True, "no volume data (index)"
    if len(prior) < MIN_VOLUME_BARS or last <= 0:
        return False, f"too few candles to judge volume (need {MIN_VOLUME_BARS})"
    avg = prior.mean()
    x = last / avg if avg else 0.0
    return x >= mult, f"volume {x:.1f}x the {len(prior)}-candle average (need {mult:g}x)"


def _f(v: Any) -> float:
    return round(float(v), 2)


# ---------------------------------------------------------------- the rules


def detect_orb(df: pd.DataFrame, symbol: str, p: dict[str, Any]) -> Setup | None:
    """First candle after 09:15-09:30 to CLOSE above the range high (buy) / below its low (sell)."""
    day = today_rows(df)
    times = day["ts"].map(_ist_time)
    rng = day[(times >= OR_START) & (times < OR_END)]
    after = day[times >= OR_END]
    if rng.empty or after.empty or after.index[-1] != df.index[-1]:
        return None
    hi, lo = float(rng["high"].max()), float(rng["low"].min())
    earlier = after.iloc[:-1]["close"]
    last = df.iloc[-1]
    close = float(last["close"])
    data = {"or_high": _f(hi), "or_low": _f(lo), "or_bars": len(rng)}
    if close > hi and not (earlier > hi).any():
        return Setup(
            "orb",
            symbol,
            "buy",
            last["ts"],
            _f(close),
            _f(hi),
            f"First close above the opening range high {hi:.2f} (range {lo:.2f}-{hi:.2f})",
            data,
        )
    if close < lo and not (earlier < lo).any():
        return Setup(
            "orb",
            symbol,
            "sell",
            last["ts"],
            _f(close),
            _f(lo),
            f"First close below the opening range low {lo:.2f} (range {lo:.2f}-{hi:.2f})",
            data,
        )
    return None


def detect_vwap_cross(df: pd.DataFrame, symbol: str, p: dict[str, Any]) -> Setup | None:
    """Close crosses today's VWAP, with volume above average."""
    if len(today_rows(df)) < 2:
        return None
    vw = ind.vwap(df, ist_dates(df))
    c = df["close"]
    x = _crossed(c.iloc[-2], vw.iloc[-2], c.iloc[-1], vw.iloc[-1])
    if not x:
        return None
    vol_ok, vol_note = _volume_ok(df, p["volume_x"], p["volume_lookback"])
    if not vol_ok:
        return None
    side: Side = "buy" if x > 0 else "sell"
    word = "above" if x > 0 else "below"
    last = df.iloc[-1]
    return Setup(
        "vwap_cross",
        symbol,
        side,
        last["ts"],
        _f(last["close"]),
        _f(vw.iloc[-1]),
        f"Closed {word} VWAP {vw.iloc[-1]:.2f}; {vol_note}",
        {"vwap": _f(vw.iloc[-1])},
    )


def detect_supertrend(df: pd.DataFrame, symbol: str, p: dict[str, Any]) -> Setup | None:
    """Supertrend direction flips on the last candle."""
    st = ind.supertrend(df, p["period"], p["multiplier"])
    d = st["direction"]
    if len(d) < 2 or np.isnan(d.iloc[-2]) or d.iloc[-1] == d.iloc[-2]:
        return None
    side: Side = "buy" if d.iloc[-1] > 0 else "sell"
    last = df.iloc[-1]
    word = "up" if side == "buy" else "down"
    return Setup(
        "supertrend",
        symbol,
        side,
        last["ts"],
        _f(last["close"]),
        _f(st["line"].iloc[-1]),
        f"Supertrend ({p['period']}, {p['multiplier']:g}) flipped {word}; "
        f"line at {st['line'].iloc[-1]:.2f}",
        {"supertrend": _f(st["line"].iloc[-1])},
    )


def detect_ema_cross(df: pd.DataFrame, symbol: str, p: dict[str, Any]) -> Setup | None:
    fast, slow = ind.ema(df["close"], p["fast"]), ind.ema(df["close"], p["slow"])
    x = _crossed(fast.iloc[-2], slow.iloc[-2], fast.iloc[-1], slow.iloc[-1]) if len(df) > 1 else 0
    if not x:
        return None
    side: Side = "buy" if x > 0 else "sell"
    last = df.iloc[-1]
    word = "above" if x > 0 else "below"
    return Setup(
        "ema_cross",
        symbol,
        side,
        last["ts"],
        _f(last["close"]),
        _f(slow.iloc[-1]),
        f"EMA {p['fast']} crossed {word} EMA {p['slow']} "
        f"({fast.iloc[-1]:.2f} vs {slow.iloc[-1]:.2f})",
        {"ema_fast": _f(fast.iloc[-1]), "ema_slow": _f(slow.iloc[-1])},
    )


def detect_rsi_reversal(df: pd.DataFrame, symbol: str, p: dict[str, Any]) -> Setup | None:
    """RSI climbs back above `oversold` (buy) or drops back below `overbought` (sell)."""
    r = ind.rsi(df["close"], p["period"])
    if len(r) < 2 or np.isnan(r.iloc[-2]) or np.isnan(r.iloc[-1]):
        return None
    prev, now = r.iloc[-2], r.iloc[-1]
    last = df.iloc[-1]
    if prev < p["oversold"] <= now:
        return Setup(
            "rsi_reversal",
            symbol,
            "buy",
            last["ts"],
            _f(last["close"]),
            None,
            f"RSI {p['period']} back above {p['oversold']} "
            f"({prev:.0f} -> {now:.0f}): oversold bounce",
            {"rsi": round(float(now), 1)},
        )
    if prev > p["overbought"] >= now:
        return Setup(
            "rsi_reversal",
            symbol,
            "sell",
            last["ts"],
            _f(last["close"]),
            None,
            f"RSI {p['period']} back below {p['overbought']} "
            f"({prev:.0f} -> {now:.0f}): overbought turn",
            {"rsi": round(float(now), 1)},
        )
    return None


def detect_breakout_volume(df: pd.DataFrame, symbol: str, p: dict[str, Any]) -> Setup | None:
    """Close beyond the high/low of the previous N candles, on above-average volume."""
    n = p["lookback"]
    if len(df) < n + 1:
        return None
    prior = df.iloc[-n - 1 : -1]
    hi, lo = float(prior["high"].max()), float(prior["low"].min())
    last = df.iloc[-1]
    close = float(last["close"])
    if lo <= close <= hi:
        return None
    vol_ok, vol_note = _volume_ok(df, p["volume_x"], n)
    if not vol_ok:
        return None
    if close > hi:
        return Setup(
            "breakout_volume",
            symbol,
            "buy",
            last["ts"],
            _f(close),
            _f(hi),
            f"Closed above the {n}-candle high {hi:.2f}; {vol_note}",
            {"high_n": _f(hi)},
        )
    return Setup(
        "breakout_volume",
        symbol,
        "sell",
        last["ts"],
        _f(close),
        _f(lo),
        f"Closed below the {n}-candle low {lo:.2f}; {vol_note}",
        {"low_n": _f(lo)},
    )


RULES: dict[str, Rule] = {
    r.key: r
    for r in (
        Rule("orb", "Opening Range Breakout", "breakout", detect_orb, {}),
        Rule(
            "vwap_cross",
            "VWAP Cross",
            "trend",
            detect_vwap_cross,
            {"volume_x": 1.2, "volume_lookback": 20},
        ),
        Rule(
            "supertrend",
            "Supertrend",
            "trend",
            detect_supertrend,
            {"period": 10, "multiplier": 3.0},
        ),
        Rule("ema_cross", "EMA Crossover", "trend", detect_ema_cross, {"fast": 9, "slow": 21}),
        Rule(
            "rsi_reversal",
            "RSI Reversal",
            "reversion",
            detect_rsi_reversal,
            {"period": 14, "oversold": 30, "overbought": 70},
        ),
        Rule(
            "breakout_volume",
            "Volume Breakout",
            "breakout",
            detect_breakout_volume,
            {"lookback": 20, "volume_x": 1.5},
        ),
    )
}


# ---------------------------------------------------------------- market mood filter


def mood_check(key: str, style: Style, side: Side, ctx: Mood | None) -> MoodCheck:
    """Does today's market mood suit this rule? Trend/breakout rules go with the market;
    reversion rules avoid fighting a strong trend."""
    if ctx is None:
        return MoodCheck(False, "No market mood yet")
    with_trend = "up" if side == "buy" else "down"
    against_trend = "down" if side == "buy" else "up"
    against_bias = "bearish" if side == "buy" else "bullish"
    word = "buy" if side == "buy" else "sell"

    if style in ("trend", "breakout"):
        if ctx.trend == against_trend:
            return MoodCheck(False, f"Market is in a {ctx.trend}trend: no {word} on a trend rule")
        if ctx.bias == against_bias:
            return MoodCheck(False, f"Market bias is {ctx.bias}: no fresh {word}")
        if key == "orb" and ctx.trend == "sideways" and ctx.strength == "weak":
            return MoodCheck(
                False, "Sideways, weak market: opening-range breakouts fail more often"
            )
        if ctx.trend == with_trend:
            return MoodCheck(True, f"Goes with the {ctx.trend}trend ({ctx.strength})")
        return MoodCheck(True, f"Market {ctx.trend}, bias {ctx.bias}: allowed")

    # reversion
    if ctx.trend == against_trend and ctx.strength == "strong":
        return MoodCheck(False, f"Strong {ctx.trend}trend: a reversal {word} fights it")
    if ctx.trend == "sideways" or ctx.strength == "weak":
        return MoodCheck(True, "Range-bound market: reversals work best here")
    return MoodCheck(True, f"Market {ctx.trend} ({ctx.strength}): allowed with care")


# ---------------------------------------------------------------- scanner


@dataclass(frozen=True)
class ScanHit:
    setup: Setup
    mood: MoodCheck
    rule_name: str

    def as_dict(self) -> dict[str, Any]:
        s = self.setup
        return {
            "rule": s.rule,
            "rule_name": self.rule_name,
            "symbol": s.symbol,
            "side": s.side,
            "bar_ts": pd.Timestamp(s.bar_ts).isoformat(),
            "price": s.price,
            "level": s.level,
            "reason": s.reason,
            "data": s.data,
            "mood_ok": self.mood.ok,
            "mood_reason": self.mood.reason,
        }


def scan(
    symbol: str,
    df: pd.DataFrame,
    ctx: Mood | None,
    rules: dict[str, dict[str, Any] | None] | None = None,
) -> list[ScanHit]:
    """Run rules (key -> params, default all) on one symbol's closed candles."""
    hits: list[ScanHit] = []
    for key, params in (rules or dict.fromkeys(RULES)).items():
        rule = RULES.get(key)
        if rule is None:
            continue
        setup = rule.detect(df, symbol, params)
        if setup:
            hits.append(ScanHit(setup, rule.mood_check(setup.side, ctx), rule.name))
    return hits
