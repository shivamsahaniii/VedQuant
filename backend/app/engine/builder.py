"""Strategy builder: user-made rules ("Build from scratch"), evaluated like the built-in rules.

A builder strategy is `params.builder`:
    {
      "mood": "trend" | "breakout" | "reversion" | "off",   # market-mood filter style
      "buy":  {"match": "all" | "any", "conditions": [...]} | null,
      "sell": {"match": "all" | "any", "conditions": [...]} | null,
    }
A condition is {"left": operand, "op": op, "right": operand}; an operand is
{"kind": <OPERANDS key>, "period": int?, "value": float?, "mult": float?}.

Like the built-in rules it only looks at CLOSED candles: the last row of `df` is the candle
that just closed, nothing later is visible (no look-ahead).
Its hits go through the same agents (entry timer,
exit planner, odds, risk, paper broker) as every other strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.engine import indicators as ind
from app.engine.setups import (
    OR_END,
    OR_START,
    MoodCheck,
    ScanHit,
    Setup,
    Side,
    _ist_time,
    ist_dates,
    mood_check,
)

RULE_KEY = "custom"
RULE_NAME = "Custom rules"
MAX_CONDITIONS = 8


@dataclass(frozen=True)
class OperandInfo:
    label: str
    period: int | None = None  # default period, None = takes no period
    max_period: int = 200


OPERANDS: dict[str, OperandInfo] = {
    "close": OperandInfo("Close"),
    "open": OperandInfo("Open"),
    "high": OperandInfo("High"),
    "low": OperandInfo("Low"),
    "volume": OperandInfo("Volume"),
    "avg_volume": OperandInfo("Average volume", 20),
    "ema": OperandInfo("EMA", 20),
    "sma": OperandInfo("SMA", 20),
    "rsi": OperandInfo("RSI", 14, 100),
    "atr": OperandInfo("ATR", 14, 100),
    "vwap": OperandInfo("VWAP"),
    "supertrend": OperandInfo("Supertrend", 10, 100),
    "or_high": OperandInfo("Opening range high"),
    "or_low": OperandInfo("Opening range low"),
    "day_high": OperandInfo("Today's high so far"),
    "day_low": OperandInfo("Today's low so far"),
    "prev_day_high": OperandInfo("Previous day high"),
    "prev_day_low": OperandInfo("Previous day low"),
    "prev_day_close": OperandInfo("Previous day close"),
    "number": OperandInfo("Number"),
}
OPS = {
    "crosses_above": "crossed above",
    "crosses_below": "crossed below",
    "above": "is above",
    "below": "is below",
}
DAY_LEVELS = {"or_high", "or_low", "prev_day_high", "prev_day_low", "prev_day_close"}
MOODS = ("trend", "breakout", "reversion", "off")


# ---------------------------------------------------------------- operand series


def _daily(df: pd.DataFrame, days: pd.Series, col: str, how: str) -> pd.Series:
    """Previous trading day's high/low/close, aligned to every row."""
    per_day = df.groupby(days)[col].agg(how)
    prev = per_day.shift(1)
    return days.map(prev).astype(float)


def _so_far(df: pd.DataFrame, days: pd.Series, col: str, how: str) -> pd.Series:
    """Today's high/low BEFORE this candle (so 'close above today's high' can happen)."""
    s = df[col].astype(float)
    run = s.groupby(days).cummax() if how == "max" else s.groupby(days).cummin()
    return run.groupby(days).shift(1)


def _opening_range(df: pd.DataFrame, days: pd.Series, col: str, how: str) -> pd.Series:
    """Today's 09:15-09:30 high/low, known only once the range is complete."""
    times = df["ts"].map(_ist_time)
    in_range = (times >= OR_START) & (times < OR_END)
    vals = df[col].astype(float).where(in_range)
    per_day = vals.groupby(days).agg(how)
    out = days.map(per_day).astype(float)
    return out.where(times >= OR_END)


def series(df: pd.DataFrame, op: dict[str, Any], days: pd.Series) -> pd.Series:
    kind = op["kind"]
    period = int(op.get("period") or OPERANDS[kind].period or 0)
    mult = float(op.get("mult") or 1)
    close = df["close"].astype(float)
    if kind == "number":
        s = pd.Series(float(op.get("value") or 0), index=df.index)
    elif kind in ("close", "open", "high", "low", "volume"):
        s = df[kind].astype(float)
    elif kind == "avg_volume":  # the candles BEFORE this one
        s = df["volume"].astype(float).shift(1).rolling(period, min_periods=period).mean()
    elif kind == "ema":
        s = ind.ema(close, period)
        s = s.where(np.arange(len(s)) >= period - 1)  # not before it has enough candles
    elif kind == "sma":
        s = close.rolling(period, min_periods=period).mean()
    elif kind == "rsi":
        s = ind.rsi(close, period)
    elif kind == "atr":
        s = ind.atr(df, period)
    elif kind == "vwap":
        s = ind.vwap(df, days)
    elif kind == "supertrend":
        s = ind.supertrend(df, period)["line"]
    elif kind in ("or_high", "or_low"):
        s = _opening_range(df, days, kind[3:], "max" if kind == "or_high" else "min")
    elif kind in ("day_high", "day_low"):
        s = _so_far(df, days, kind[4:], "max" if kind == "day_high" else "min")
    elif kind.startswith("prev_day_"):
        col = kind.removeprefix("prev_day_")
        s = _daily(df, days, col, {"high": "max", "low": "min", "close": "last"}[col])
    else:  # pragma: no cover - the schema only lets known kinds in
        raise ValueError(f"Unknown operand {kind}")
    return s.astype(float) * mult


def label(op: dict[str, Any]) -> str:
    kind = op["kind"]
    if kind == "number":
        return f"{float(op.get('value') or 0):g}"
    info = OPERANDS[kind]
    text = info.label
    if info.period is not None:
        text += f"({int(op.get('period') or info.period)})"
    mult = float(op.get("mult") or 1)
    return f"{mult:g}× {text}" if mult != 1 else text


# ---------------------------------------------------------------- evaluation


@dataclass(frozen=True)
class CondResult:
    ok: bool
    text: str
    level: float | None  # the value it crossed, for the stop at "level"


def _check(df: pd.DataFrame, cond: dict[str, Any], days: pd.Series) -> CondResult:
    a = series(df, cond["left"], days)
    b = series(df, cond["right"], days)
    a1, b1 = float(a.iloc[-1]), float(b.iloc[-1])
    op = cond["op"]
    words = f"{label(cond['left'])} {OPS[op]} {label(cond['right'])}"
    if np.isnan(a1) or np.isnan(b1):
        return CondResult(False, f"{words}: not enough data yet", None)
    if op in ("above", "below"):
        ok = a1 > b1 if op == "above" else a1 < b1
        return CondResult(ok, f"{words} ({a1:.2f} vs {b1:.2f})", None)
    if len(df) < 2:
        return CondResult(False, f"{words}: needs two candles", None)
    a0, b0 = float(a.iloc[-2]), float(b.iloc[-2])
    # A level that became known on this candle (the opening range at 09:30, a new day's previous
    # high): the candle before is compared with the same level, so the first break counts.
    if np.isnan(b0) and cond["right"]["kind"] in DAY_LEVELS:
        b0 = b1
    if np.isnan(a0) or np.isnan(b0):
        return CondResult(False, f"{words}: not enough data yet", None)
    up = a0 <= b0 and a1 > b1
    down = a0 >= b0 and a1 < b1
    ok = up if op == "crosses_above" else down
    level = b1 if cond["right"]["kind"] != "number" else None
    return CondResult(ok, f"{words} ({a1:.2f} vs {b1:.2f})", level)


def evaluate(df: pd.DataFrame, group: dict[str, Any]) -> tuple[bool, list[CondResult]]:
    """Check one side's conditions on the last closed candle."""
    if df.empty or not group or not group.get("conditions"):
        return False, []
    days = ist_dates(df)
    results = [_check(df, c, days) for c in group["conditions"]]
    hit = (
        all(r.ok for r in results)
        if group.get("match", "all") == "all"
        else any(r.ok for r in results)
    )
    return hit, results


def _context(df: pd.DataFrame, days: pd.Series) -> dict[str, Any]:
    """Opening range of today, when complete, so the exit planner's range stops work too."""
    hi = _opening_range(df, days, "high", "max").iloc[-1]
    lo = _opening_range(df, days, "low", "min").iloc[-1]
    if np.isnan(hi) or np.isnan(lo):
        return {}
    return {"or_high": round(float(hi), 2), "or_low": round(float(lo), 2)}


def scan_builder(symbol: str, df: pd.DataFrame, ctx: Any, spec: dict[str, Any]) -> list[ScanHit]:
    """The builder's version of setups.scan: at most one hit per side on the closed candle."""
    if df.empty:
        return []
    df = df.reset_index(drop=True)
    hits: list[ScanHit] = []
    for side in ("buy", "sell"):
        group = spec.get(side)
        ok, results = evaluate(df, group or {})
        if not ok:
            continue
        passed = [r for r in results if r.ok]
        level = next((r.level for r in passed if r.level is not None), None)
        setup = Setup(
            rule=RULE_KEY,
            symbol=symbol,
            side=side,
            bar_ts=df["ts"].iloc[-1],
            price=round(float(df["close"].iloc[-1]), 2),
            level=round(level, 2) if level is not None else None,
            reason="; ".join(r.text for r in passed),
            data=_context(df, ist_dates(df)),
        )
        hits.append(ScanHit(setup, _mood(spec.get("mood", "trend"), side, ctx), RULE_NAME))
    return hits


def _mood(style: str, side: Side, ctx: Any) -> MoodCheck:
    if style == "off":
        return MoodCheck(True, "Market mood filter is off for this strategy")
    return mood_check(RULE_KEY, style, side, ctx)  # type: ignore[arg-type]


def catalog() -> dict[str, Any]:
    """What the builder offers, for the strategy dialog."""
    return {
        "operands": [
            {"kind": k, "label": v.label, "period": v.period, "max_period": v.max_period}
            for k, v in OPERANDS.items()
        ],
        "ops": [{"key": k, "label": v} for k, v in OPS.items()],
        "moods": list(MOODS),
        "max_conditions": MAX_CONDITIONS,
    }
