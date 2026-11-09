"""Odds agent ("time machine"): how often does this plan hit the target first, the stop first,
or neither, if the rest of today behaves like this stock's own recent sessions?

Method (after Jake Schincariol's day-trader-skill, MIT, adapted to NSE 09:15-15:30):
  1. Pool: every past FULL session's 5-minute candles, as ratios to the previous candle's close,
     grouped by time-of-day slot (09:15 = slot 0 ... 15:25 = slot 74).
  2. One replay: from the entry, for every slot left until the square-off, draw a past candle from
     the same slot (+/- `window` slots) and scale it to the current price. Stop is checked before
     target, so a candle touching both counts as a loss (conservative).
  3. Thousands of replays -> odds. Seeded from the signal's trigger key, so the same signal always
     gives the same numbers and anyone can re-run it.
  4. Verdict: a target R times the risk away needs to win 1 / (1 + R) of decided replays to break
     even. It is reported as close to break-even / leans / strongly toward target or stop.

This is a simulation from recent history, not a prediction: news, results and gaps can do things the
last sessions never did. The verdict is the signal's confidence, shown with that caveat.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from typing import Any

import pandas as pd

from app.engine.nse import IST, SESSION

SLOT_MINUTES = 5
SESSION_SLOTS = 75  # 09:15 .. 15:25 five-minute candles
MIN_SESSION_FILL = 0.9  # a session counts as full with >= 90 % of its candles
MIN_SESSIONS = 15


@dataclass(frozen=True)
class Odds:
    replays: int
    sessions: int
    seed: int
    target_first: float  # percentages
    stop_first: float
    neither: float
    green: float
    median_close: float
    p5_close: float
    p95_close: float
    avg_r: float
    breakeven: float  # win share of decided replays needed to break even
    win_share: float  # actual win share of decided replays
    verdict: str
    lean: str  # target | stop | even

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class NoOdds:
    reason: str


def slot_of(ts: Any) -> int:
    t = pd.Timestamp(ts).tz_convert(IST)
    return ((t.hour * 60 + t.minute) - (9 * 60 + 15)) // SLOT_MINUTES


def build_pool(df: pd.DataFrame, before: datetime) -> tuple[list[list[tuple]], int]:
    """Past full sessions (IST days before `before`) -> per-slot (o, h, l, c) ratios."""
    pool: list[list[tuple]] = [[] for _ in range(SESSION_SLOTS)]
    if df.empty:
        return pool, 0
    d = df.copy()
    local = pd.to_datetime(d["ts"], utc=True).dt.tz_convert(IST)
    d["day"], d["slot"] = local.dt.date, d["ts"].map(slot_of)
    d = d[
        (d["slot"] >= 0) & (d["slot"] < SESSION_SLOTS) & (d["day"] < before.astimezone(IST).date())
    ]
    sessions = 0
    for _, s in d.groupby("day"):
        if len(s) < SESSION_SLOTS * MIN_SESSION_FILL:
            continue
        sessions += 1
        s = s.sort_values("slot")
        prev = s["close"].shift(1).fillna(s["open"])
        for slot, o, h, lo, c, pc in zip(
            s["slot"], s["open"], s["high"], s["low"], s["close"], prev, strict=True
        ):
            if pc > 0:
                pool[int(slot)].append((o / pc, h / pc, lo / pc, c / pc))
    return pool, sessions


def seed_for(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(q * (len(xs) - 1) + 0.5)))]


def _verdict(win: float, need: float, r: float) -> tuple[str, str]:
    diff = (win - need) * 100
    if abs(diff) < 5:
        return ("Close to a coin flip" if abs(r - 1) < 0.05 else "Close to break-even"), "even"
    side = "target" if diff > 0 else "stop"
    return (f"Strongly toward the {side}" if abs(diff) >= 15 else f"Leans toward the {side}"), side


def simulate(
    pool: list[list[tuple]],
    sessions: int,
    side: str,
    entry: Decimal,
    stop: Decimal,
    target: Decimal,
    entry_time: datetime,
    *,
    key: str,
    replays: int = 3000,
    window: int = 2,
    until: time = SESSION.square_off,
    min_sessions: int = MIN_SESSIONS,
) -> Odds | NoOdds:
    if sessions < min_sessions:
        return NoOdds(f"Needs {min_sessions} past full sessions of this stock, has {sessions}")
    long = side == "buy"
    e, st, tg = float(entry), float(stop), float(target)
    risk = abs(e - st)
    r_target = abs(tg - e) / risk
    first = slot_of(entry_time)  # the slot that starts at the entry time
    last = (until.hour * 60 + until.minute - (9 * 60 + 15)) // SLOT_MINUTES - 1
    if first > last:
        return NoOdds("No time left before the square-off")
    seed = seed_for(key)
    rng = random.Random(seed)  # noqa: S311 - simulation, not security
    counts = {"target": 0, "stop": 0, "neither": 0}
    closes, rs, green = [], [], 0
    for _ in range(replays):
        p, out = e, None
        for i in range(first, last + 1):
            j = min(SESSION_SLOTS - 1, max(0, i + rng.randint(-window, window)))
            bucket = pool[j] or pool[i]
            if not bucket:
                continue
            _, h, lo, c = rng.choice(bucket)
            hi, low = p * h, p * lo
            if out is None:
                if (long and low <= st) or (not long and hi >= st):
                    out = "stop"
                elif (long and hi >= tg) or (not long and low <= tg):
                    out = "target"
            p = p * c
        out = out or "neither"
        counts[out] += 1
        closes.append(p)
        r = (
            r_target
            if out == "target"
            else -1.0 if out == "stop" else ((p - e) / risk if long else (e - p) / risk)
        )
        rs.append(r)
        if out == "target" or (out == "neither" and ((p > e) if long else (p < e))):
            green += 1
    decided = counts["target"] + counts["stop"]
    need = 1 / (1 + r_target)
    win = counts["target"] / decided if decided else 0.0
    verdict, lean = (
        _verdict(win, need, r_target)
        if decided
        else ("Rarely decided by " "the square-off", "even")
    )
    pc = 100 / replays
    return Odds(
        replays=replays,
        sessions=sessions,
        seed=seed,
        target_first=round(counts["target"] * pc, 1),
        stop_first=round(counts["stop"] * pc, 1),
        neither=round(counts["neither"] * pc, 1),
        green=round(green * pc, 1),
        median_close=round(_pct(closes, 0.5), 2),
        p5_close=round(_pct(closes, 0.05), 2),
        p95_close=round(_pct(closes, 0.95), 2),
        avg_r=round(sum(rs) / len(rs), 3),
        breakeven=round(need * 100, 1),
        win_share=round(win * 100, 1),
        verdict=verdict,
        lean=lean,
    )
