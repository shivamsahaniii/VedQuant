"""Odds agent (time machine) and Risk Manager + Sizer."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engine.exit_plan import ExitPlan
from app.engine.odds import SESSION_SLOTS, NoOdds, Odds, build_pool, simulate
from app.risk.engine import AccountState, RiskLimits, check_entry, check_exit, size

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 11, 10)


def at(h, m, day=TODAY):
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(UTC)


def sessions(n, bars=SESSION_SLOTS, seed=1, end=TODAY):
    rng = np.random.default_rng(seed)
    rows, px = [], 1000.0
    for k in range(n):
        day = end - timedelta(days=n - k)
        for i in range(bars):
            o = px
            c = o * (1 + rng.normal(0, 0.001))
            rows.append(
                {
                    "ts": pd.Timestamp(at(9, 15, day) + timedelta(minutes=5 * i)),
                    "open": o,
                    "high": max(o, c) * 1.0005,
                    "low": min(o, c) * 0.9995,
                    "close": c,
                    "volume": 1000,
                }
            )
            px = c
    return pd.DataFrame(rows)


def flat_pool(*candles):
    return [list(candles) for _ in range(SESSION_SLOTS)]


def run(pool, side="buy", entry="1000", stop="990", target="1010", key="k", n=20, **kw):
    return simulate(pool, n, side, D(entry), D(stop), D(target), at(10, 0), key=key, **kw)


# ---------------------------------------------------------------- odds


def test_pool_uses_only_full_past_sessions():
    df = pd.concat(
        [sessions(20), sessions(1, bars=30, seed=2, end=TODAY - timedelta(days=30))],
        ignore_index=True,
    )
    today = sessions(1, seed=3)
    today["ts"] = [pd.Timestamp(at(9, 15) + timedelta(minutes=5 * i)) for i in range(len(today))]
    pool, n = build_pool(pd.concat([df, today], ignore_index=True), at(10, 0))
    assert n == 20  # the 30-candle half session and today are left out
    assert all(len(b) == 20 for b in pool)


def test_same_signal_same_numbers():
    pool, n = build_pool(sessions(20), at(10, 0))
    a = run(pool, n=n, key="orb:SBIN:buy:2026-11-10", replays=500)
    b = run(pool, n=n, key="orb:SBIN:buy:2026-11-10", replays=500)
    c = run(pool, n=n, key="orb:TCS:buy:2026-11-10", replays=500)
    assert a == b and a.seed != c.seed
    assert round(a.target_first + a.stop_first + a.neither, 1) == 100.0


def test_rising_market_strongly_favours_the_target():
    o = run(flat_pool((1, 1.0025, 0.9995, 1.002)), replays=300)
    assert isinstance(o, Odds) and o.target_first == 100.0 and o.lean == "target"
    assert o.verdict == "Strongly toward the target"


def test_symmetric_market_is_a_coin_flip_at_1r():
    up, down = (1, 1.003, 0.999, 1.002), (1, 1.001, 0.997, 0.998)
    o = run(flat_pool(up, down), replays=3000)
    assert abs(o.win_share - 50) < 5 and o.verdict == "Close to a coin flip"
    assert o.breakeven == 50.0


def test_a_candle_touching_both_counts_as_the_stop():
    o = run(flat_pool((1, 1.05, 0.95, 1.0)), replays=100)
    assert o.stop_first == 100.0


def test_breakeven_depends_on_the_target_r():
    o = run(flat_pool((1, 1.0025, 0.9995, 1.002)), target="1020", replays=50)
    assert o.breakeven == 33.3  # a 2R target only needs to win 1 in 3


def test_not_enough_history():
    r = run(flat_pool((1, 1, 1, 1)), n=5)
    assert isinstance(r, NoOdds) and "15 past full sessions" in r.reason


def test_short_side():
    o = run(
        flat_pool((1, 1.0005, 0.9975, 0.998)), side="sell", stop="1010", target="990", replays=100
    )
    assert o.target_first == 100.0


# ---------------------------------------------------------------- risk + sizing

PLAN = ExitPlan(
    side="buy",
    entry=D("1167.40"),
    stop=D("1165.20"),
    target=D("1171.80"),
    tick=D("0.05"),
    stop_rule="or_mid",
    risk_per_share=D("2.20"),
    reward_per_share=D("4.40"),
    reward_risk=D("2.00"),
    cost_pct=D("0.106"),
    flat_by="15:15",
)
LIM = RiskLimits()
ACCT = AccountState(cash=D("100000"))
NOW = at(10, 6)


def test_sizing_takes_the_smallest_limit():
    qty, by, limits = size(PLAN, LIM, D("100000"))
    assert limits["risk per trade"] == 454  # 1 % of 1,00,000 = 1,000 / 2.20
    assert limits["position size"] == 28  # 33 % of capital / 1,167.40
    assert (qty, by) == (28, "position size")


def test_approved_trade():
    a = check_entry(PLAN, "SBIN", LIM, ACCT, NOW)
    assert a.ok and a.qty == 28
    assert a.max_loss == D("61.60") and a.target_profit == D("123.20")
    assert a.charges.total > 0 and a.target_profit >= 2 * a.charges.total


@pytest.mark.parametrize(
    "acct, lim, now, check",
    [
        (replace(ACCT, kill_switch=True), LIM, NOW, "kill switch"),
        (replace(ACCT, halted=True), LIM, NOW, "halted"),
        (ACCT, LIM, at(14, 45), "window"),
        (ACCT, LIM, at(9, 20), "window"),
        (replace(ACCT, loss_today=D("3000")), LIM, NOW, "daily loss"),
        (replace(ACCT, trades_today=5), LIM, NOW, "trades"),
        (replace(ACCT, open_positions=3), LIM, NOW, "open positions"),
        (replace(ACCT, open_symbols=frozenset({"SBIN"})), LIM, NOW, "duplicate"),
        (ACCT, replace(LIM, capital=D("1000")), NOW, "size"),
        (replace(ACCT, loss_today=D("2900"), committed_risk=D("100")), LIM, NOW, "daily loss"),
        (ACCT, replace(LIM, min_profit_multiple=D("10")), NOW, "charges"),
    ],
)
def test_each_block(acct, lim, now, check):
    b = check_entry(PLAN, "SBIN", lim, acct, now)
    assert not b.ok and b.check == check, b


def test_daily_loss_room_shrinks_the_size():
    a = check_entry(PLAN, "SBIN", LIM, replace(ACCT, loss_today=D("2950")), NOW)
    assert a.ok and a.qty == 22 and a.sized_by == "daily loss room"  # 50 / 2.20


def test_exits_are_never_blocked_by_limits():
    assert check_exit(42, 42).ok
    assert not check_exit(0, 1).ok
    assert not check_exit(10, 11).ok


def test_leftover_cash_does_not_make_crumb_trades():
    # Two positions already use the cash: the normal size is 28, the cash left buys 3.
    low_cash = replace(ACCT, cash=D("4000"), open_positions=2)
    b = check_entry(PLAN, "SBIN", LIM, low_cash, NOW)
    assert not b.ok and b.check == "size" and "Too small to be worth it" in b.reason
    # Enough cash for a third of the normal size or more: taken, sized by the cash.
    ok = check_entry(PLAN, "SBIN", LIM, replace(ACCT, cash=D("12000"), open_positions=2), NOW)
    assert ok.ok and ok.qty == 10 and ok.sized_by == "cash"
