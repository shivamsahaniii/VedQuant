"""Technical indicators on candle DataFrames (columns: open, high, low, close, volume).

Floats are fine here (indicators, not money). Every function only looks at the current and
past rows (no look-ahead), so the value at row i is what a trader knew when bar i closed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average. NaN until `period` values exist."""
    out = series.ewm(span=period, adjust=False, min_periods=period).mean()
    return out


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing): the typical size of one candle's move."""
    return true_range(df).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder): trend strength 0-100, direction-free."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(df)
    alpha = 1 / period
    atr_ = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr_
    minus_di = (
        100 * pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr_
    )
    denom = plus_di + minus_di
    # No directional movement at all (0/0) means no trend: DX = 0, not undefined.
    dx = (100 * (plus_di - minus_di).abs() / denom.replace(0, np.nan)).where(denom != 0, 0.0)
    dx = dx.where(atr_.notna())  # still NaN before enough bars
    return dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


def vwap(df: pd.DataFrame, day: pd.Series) -> pd.Series:
    """Volume-weighted average price, restarting each day. `day` = trading date per row.

    Rows with no volume (an index) fall back to an equal-weight average of typical price.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].astype(float)
    weights = vol.where(vol > 0, 1.0)
    pv = (typical * weights).groupby(day).cumsum()
    return pv / weights.groupby(day).cumsum()


def slope(series: pd.Series, lookback: int = 5) -> pd.Series:
    """Change over the last `lookback` rows, as a fraction of the value."""
    return series / series.shift(lookback) - 1


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder), 0-100. NaN until `period` changes exist."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    out = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    # No losses at all = 100, no gains at all = 0, no movement = 50.
    out = out.where(loss != 0, np.where(gain > 0, 100.0, 50.0))
    return out.where(gain.notna())


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Supertrend line and direction (+1 up, -1 down). NaN until the ATR exists.

    Bands = (high + low) / 2 +/- multiplier x ATR. The final bands only tighten while the trend
    holds; direction flips when the close crosses the opposite band. Row i uses rows <= i only.
    """
    atr_ = atr(df, period).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    line = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    upper = lower = np.nan
    for i in range(n):
        if np.isnan(atr_[i]):
            continue
        bu, bl = hl2[i] + multiplier * atr_[i], hl2[i] - multiplier * atr_[i]
        if np.isnan(upper):  # first bar with an ATR
            upper, lower = bu, bl
            d = 1.0 if close[i] >= hl2[i] else -1.0
        else:
            prev_close = close[i - 1]
            upper = bu if (bu < upper or prev_close > upper) else upper
            lower = bl if (bl > lower or prev_close < lower) else lower
            d = direction[i - 1]
            if d == -1 and close[i] > upper:
                d = 1.0
            elif d == 1 and close[i] < lower:
                d = -1.0
        direction[i] = d
        line[i] = lower if d == 1 else upper
    return pd.DataFrame({"line": line, "direction": direction}, index=df.index)
