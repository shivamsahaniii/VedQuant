"""Market context ("market mood"): read the market before any strategy is allowed to act.

Inputs: NIFTY candles (today and earlier), plus each stock's day open and latest price.
Output: trend, strength, volatility, breadth, session phase and an overall bias, each with
a plain-English reason. Pure function: no I/O, fully unit-tested.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd

from app.engine.indicators import adx, atr, ema, vwap

IST = ZoneInfo("Asia/Kolkata")

Trend = Literal["up", "down", "sideways"]
Strength = Literal["strong", "moderate", "weak"]
Volatility = Literal["high", "normal", "low"]
Bias = Literal["bullish", "bearish", "neutral"]

EMA_PERIOD = 20
MIN_BARS = EMA_PERIOD  # fewer bars than this = still warming up
SLOPE_BARS = 5
SLOPE_MIN_ATR = 0.3  # EMA must move >= 0.3 ATR over 5 bars to count as rising/falling
ADX_STRONG, ADX_MODERATE = 25.0, 18.0
# Typical NIFTY 5-minute candle is ~0.10% of price. Scaled by sqrt(minutes/5) for other bars.
ATR_PCT_HIGH_5M, ATR_PCT_LOW_5M = 0.20, 0.06
BREADTH_BROAD = 0.70
FLAT_PCT = 0.05  # a stock within +/-0.05% of its open counts as flat


@dataclass
class Breadth:
    up: int = 0
    down: int = 0
    flat: int = 0

    @property
    def total(self) -> int:
        return self.up + self.down + self.flat

    @property
    def label(self) -> str:
        if not self.total:
            return "unknown"
        if self.up / self.total >= BREADTH_BROAD:
            return "broad up"
        if self.down / self.total >= BREADTH_BROAD:
            return "broad down"
        return "mixed"


@dataclass
class MarketContext:
    as_of: datetime
    timeframe: str
    bars: int
    warming_up: bool
    trend: Trend
    strength: Strength
    volatility: Volatility
    breadth: Breadth
    phase: str
    bias: Bias
    summary: str
    index: dict[str, float | None] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        d["breadth"] = {
            "up": self.breadth.up,
            "down": self.breadth.down,
            "flat": self.breadth.flat,
            "total": self.breadth.total,
            "label": self.breadth.label,
        }
        return d


def session_phase(now: datetime) -> str:
    t = now.astimezone(IST).time()
    if now.astimezone(IST).weekday() >= 5:
        return "closed"
    if t < time(9, 15):
        return "pre-open"
    if t < time(9, 45):
        return "opening"
    if t < time(14, 30):
        return "mid-day"
    if t < time(15, 30):
        return "closing"
    return "closed"


def _minutes(timeframe: str) -> int:
    return {"1m": 1, "5m": 5, "15m": 15, "1h": 60}.get(timeframe, 5)


def breadth_of(stocks: dict[str, tuple[float, float]]) -> Breadth:
    """stocks: symbol -> (day open, latest price)."""
    b = Breadth()
    for open_, last in stocks.values():
        if not open_:
            continue
        pct = (last / open_ - 1) * 100
        if pct > FLAT_PCT:
            b.up += 1
        elif pct < -FLAT_PCT:
            b.down += 1
        else:
            b.flat += 1
    return b


def compute_context(
    index: pd.DataFrame,
    stocks: dict[str, tuple[float, float]],
    now: datetime,
    timeframe: str = "5m",
) -> MarketContext:
    """`index`: NIFTY candles sorted by ts (UTC) with open/high/low/close/volume (floats)."""
    df = index.reset_index(drop=True)
    bars = len(df)
    breadth = breadth_of(stocks)
    phase = session_phase(now)
    reasons: list[str] = []

    if bars == 0:
        return MarketContext(
            now,
            timeframe,
            0,
            True,
            "sideways",
            "weak",
            "normal",
            breadth,
            phase,
            "neutral",
            "Waiting for market data",
            {},
            ["No NIFTY candles yet"],
        )

    day = df["ts"].dt.tz_convert(IST).dt.date
    close = float(df["close"].iloc[-1])
    today = day == day.iloc[-1]
    day_open = float(df.loc[today, "open"].iloc[0])
    day_change_pct = (close / day_open - 1) * 100

    ema_s = ema(df["close"], EMA_PERIOD)
    vwap_s = vwap(df, day)
    atr_s = atr(df, 14)
    adx_s = adx(df, 14)
    e = _num(ema_s.iloc[-1])
    v = _num(vwap_s.iloc[-1])
    a = _num(atr_s.iloc[-1])
    x = _num(adx_s.iloc[-1])
    warming_up = bars < MIN_BARS or e is None

    # ---- trend
    if warming_up or e is None:
        trend: Trend = (
            "up" if day_change_pct > 0.15 else "down" if day_change_pct < -0.15 else "sideways"
        )
        reasons.append(
            f"Warming up ({bars} of {MIN_BARS} candles): trend from today's move only "
            f"({day_change_pct:+.2f}% since open)"
        )
    else:
        prev = _num(ema_s.iloc[-1 - SLOPE_BARS]) if bars > SLOPE_BARS else None
        slope_atr = ((e - prev) / a) if (prev is not None and a) else 0.0
        above_ema, above_vwap = close > e, (v is not None and close > v)
        below_ema, below_vwap = close < e, (v is not None and close < v)
        if above_ema and above_vwap and slope_atr > SLOPE_MIN_ATR:
            trend = "up"
        elif below_ema and below_vwap and slope_atr < -SLOPE_MIN_ATR:
            trend = "down"
        else:
            trend = "sideways"
        reasons.append(
            f"NIFTY {close:,.2f} is {'above' if above_ema else 'below'} EMA{EMA_PERIOD} {e:,.2f}"
            + (f" and {'above' if above_vwap else 'below'} VWAP {v:,.2f}" if v is not None else "")
        )
        direction = (
            "rising"
            if slope_atr > SLOPE_MIN_ATR
            else "falling" if slope_atr < -SLOPE_MIN_ATR else "flat"
        )
        reasons.append(
            f"EMA{EMA_PERIOD} is {direction} ({slope_atr:+.2f} ATR over {SLOPE_BARS} candles)"
        )

    # ---- strength
    if x is None:
        strength: Strength = "weak"
        reasons.append("Trend strength not known yet (ADX needs more candles)")
    else:
        strength = "strong" if x >= ADX_STRONG else "moderate" if x >= ADX_MODERATE else "weak"
        reasons.append(
            f"ADX {x:.0f}: {strength} trend" + (" (choppy)" if strength == "weak" else "")
        )

    # ---- volatility
    atr_pct = (a / close * 100) if (a and close) else None
    scale = math.sqrt(_minutes(timeframe) / 5)
    if atr_pct is None:
        volatility: Volatility = "normal"
    elif atr_pct > ATR_PCT_HIGH_5M * scale:
        volatility = "high"
    elif atr_pct < ATR_PCT_LOW_5M * scale:
        volatility = "low"
    else:
        volatility = "normal"
    if atr_pct is not None:
        reasons.append(
            f"Average {timeframe} candle is {atr_pct:.2f}% of price: {volatility} volatility"
        )

    # ---- breadth
    if breadth.total:
        reasons.append(
            f"{breadth.up} of {breadth.total} stocks up, {breadth.down} down "
            f"since open ({breadth.label})"
        )

    # ---- bias
    if trend == "up" and breadth.label != "broad down":
        bias: Bias = "bullish"
    elif trend == "down" and breadth.label != "broad up":
        bias = "bearish"
    else:
        bias = "neutral"

    trend_word = {"up": "Uptrend", "down": "Downtrend", "sideways": "Sideways"}[trend]
    moving = (
        f"{breadth.up}/{breadth.total} stocks rising"
        if breadth.up >= breadth.down
        else f"{breadth.down}/{breadth.total} stocks falling"
    )
    parts = [trend_word, strength, f"{volatility} volatility"]
    if breadth.total:
        parts.append(moving)
    parts.append(phase)
    summary = " · ".join(parts)

    return MarketContext(
        as_of=now,
        timeframe=timeframe,
        bars=bars,
        warming_up=warming_up,
        trend=trend,
        strength=strength,
        volatility=volatility,
        breadth=breadth,
        phase=phase,
        bias=bias,
        summary=summary,
        index={
            "ltp": close,
            "day_open": day_open,
            "change_pct": round(day_change_pct, 2),
            "ema20": _round(e),
            "vwap": _round(v),
            "adx": _round(x, 1),
            "atr_pct": _round(atr_pct, 3),
        },
        reasons=reasons,
    )


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _round(v: float | None, places: int = 2) -> float | None:
    return None if v is None else round(v, places)
