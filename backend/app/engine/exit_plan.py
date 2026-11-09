"""Exit Planner agent: stop loss and target, decided BEFORE the entry.

Stop rules:
  auto      the rule's natural invalidation point (ORB -> range midpoint, Supertrend -> its line,
            VWAP cross -> VWAP, others -> 1.5 x ATR)
  or_mid    opening-range midpoint            or_far   the far side of the opening range
  level     the level the setup crossed       atr:K    K x ATR(14) from the entry
  pct:X     X % from the entry

Real-market guards:
  * stop rounded to the NSE tick AWAY from the entry, target rounded TOWARD it (both conservative),
  * refuse a stop too tight to survive normal noise and the spread (min_risk_pct, min 3 ticks),
  * refuse a stop so wide that one trade risks too much of the price (max_risk_pct),
  * refuse a target that cannot pay the round-trip charges `min_profit_multiple` times over,
  * every intraday plan is flat by the square-off time (15:15 IST).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from app.engine import indicators as ind
from app.engine.nse import SESSION, round_to_tick, tick_size, to_dec
from app.engine.setups import Setup
from app.risk.charges import Product, cost_pct_estimate

AUTO_STOP = {"orb": "or_mid", "supertrend": "level", "vwap_cross": "level"}
MIN_TICKS = 3


@dataclass(frozen=True)
class ExitParams:
    stop: str = "auto"
    target_r: Decimal = Decimal("2")
    min_risk_pct: Decimal = Decimal("0.10")
    max_risk_pct: Decimal = Decimal("2.0")
    min_profit_multiple: Decimal = Decimal("2")
    product: Product = "intraday"


@dataclass(frozen=True)
class ExitPlan:
    side: str
    entry: Decimal
    stop: Decimal
    target: Decimal
    tick: Decimal
    stop_rule: str
    risk_per_share: Decimal
    reward_per_share: Decimal
    reward_risk: Decimal
    cost_pct: Decimal
    flat_by: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}
        d["notes"] = list(self.notes)
        return d


@dataclass(frozen=True)
class Refused:
    reason: str


def _atr(df: pd.DataFrame) -> tuple[float, str | None]:
    a = ind.atr(df, 14).iloc[-1] if len(df) else np.nan
    if not np.isnan(a):
        return float(a), None
    tr = ind.true_range(df).dropna()
    if tr.empty:
        return float("nan"), None
    return float(tr.mean()), f"ATR from only {len(tr)} candles"


def _raw_stop(rule: str, setup: Setup, entry: Decimal, df: pd.DataFrame, notes: list[str]):
    long = setup.side == "buy"
    d = setup.data
    if rule == "or_mid":
        if "or_high" not in d:
            return None, "This setup has no opening range"
        return (to_dec(d["or_high"]) + to_dec(d["or_low"])) / 2, None
    if rule == "or_far":
        if "or_high" not in d:
            return None, "This setup has no opening range"
        return to_dec(d["or_low"] if long else d["or_high"]), None
    if rule == "level":
        if setup.level is None:
            return None, "This setup has no level to put the stop at"
        return to_dec(setup.level), None
    if rule.startswith("atr:"):
        k = to_dec(rule[4:])
        a, note = _atr(df)
        if np.isnan(a):
            return None, "Not enough candles for an ATR stop"
        if note:
            notes.append(note)
        dist = k * to_dec(round(a, 4))
        return (entry - dist) if long else (entry + dist), None
    if rule.startswith("pct:"):
        dist = entry * to_dec(rule[4:]) / 100
        return (entry - dist) if long else (entry + dist), None
    return None, f"Unknown stop rule '{rule}'"


def plan_exit(
    setup: Setup,
    entry: Decimal,
    df: pd.DataFrame,
    params: ExitParams | None = None,
    instrument_tick: Decimal | None = None,
) -> ExitPlan | Refused:
    p = params or ExitParams()
    long = setup.side == "buy"
    tick = tick_size(entry, instrument_tick)
    rule = AUTO_STOP.get(setup.rule, "atr:1.5") if p.stop == "auto" else p.stop
    notes: list[str] = []

    raw, err = _raw_stop(rule, setup, entry, df, notes)
    if err:
        return Refused(err)
    stop = round_to_tick(raw, tick, up=not long)  # away from the entry
    if (long and stop >= entry) or (not long and stop <= entry):
        return Refused(f"Stop {stop} is on the wrong side of the entry {entry}")

    risk = abs(entry - stop)
    min_risk = max(entry * p.min_risk_pct / 100, tick * MIN_TICKS)
    if risk < min_risk:
        return Refused(
            f"Stop too tight: {risk} a share is under {min_risk.quantize(tick)} "
            f"(normal noise and the spread would hit it)"
        )
    risk_pct = risk / entry * 100
    if risk_pct > p.max_risk_pct:
        return Refused(f"Stop too wide: {risk_pct:.2f}% of the price (max {p.max_risk_pct}%)")

    raw_target = entry + p.target_r * risk if long else entry - p.target_r * risk
    target = round_to_tick(raw_target, tick, up=not long)  # toward the entry
    reward = abs(target - entry)

    cost_pct = cost_pct_estimate(p.product)
    reward_pct = reward / entry * 100
    if reward_pct < p.min_profit_multiple * cost_pct:
        return Refused(
            f"Target too small: {reward_pct:.3f}% move cannot pay ~{cost_pct:.3f}% charges "
            f"{p.min_profit_multiple}x over"
        )

    return ExitPlan(
        side=setup.side,
        entry=entry,
        stop=stop,
        target=target,
        tick=tick,
        stop_rule=rule,
        risk_per_share=risk,
        reward_per_share=reward,
        reward_risk=(reward / risk).quantize(Decimal("0.01")),
        cost_pct=cost_pct.quantize(Decimal("0.0001")),
        flat_by=SESSION.square_off.strftime("%H:%M") if p.product == "intraday" else "",
        notes=notes,
    )
