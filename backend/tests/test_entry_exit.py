"""Entry Timer, Exit Planner, NSE rules and charges."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.engine.entry import EntryParams, decide_entry, trigger_key
from app.engine.exit_plan import ExitParams, ExitPlan, Refused, plan_exit
from app.engine.nse import TradingCalendar, round_to_tick, tick_size
from app.engine.setups import MoodCheck, ScanHit, Setup
from app.risk.charges import cost_pct_estimate, round_trip

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 10)  # Tuesday


def at(h, m, s=0, day=DAY):
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=IST).astimezone(UTC)


def orb_setup(side="buy", price=102.2, level=101.5, hi=101.5, lo=98.5, bar=(10, 0)):
    return Setup(
        "orb",
        "SBIN",
        side,
        pd.Timestamp(at(*bar)),
        price,
        level,
        "test",
        {"or_high": hi, "or_low": lo, "or_bars": 3},
    )


def hit(setup=None, ok=True):
    return ScanHit(
        setup or orb_setup(),
        MoodCheck(ok, "Goes with the uptrend" if ok else "no"),
        "Opening Range Breakout",
    )


# ---------------------------------------------------------------- NSE rules


def test_tick_size_prefers_the_instrument():
    assert tick_size(D("1200"), D("0.05")) == D("0.05")
    assert tick_size(D("120")) == D("0.01")
    assert tick_size(D("820")) == D("0.05")
    assert tick_size(D("3600")) == D("0.10")
    assert round_to_tick(D("1165.225"), D("0.05"), up=False) == D("1165.20")
    assert round_to_tick(D("1165.225"), D("0.05"), up=True) == D("1165.25")


def test_calendar_weekends_and_holidays():
    cal = TradingCalendar(["2026-11-10"])
    assert not cal.is_trading_day(date(2026, 11, 10))
    assert not cal.is_trading_day(date(2026, 11, 14))  # Saturday
    assert cal.is_trading_day(date(2026, 11, 11))
    assert TradingCalendar().is_open(at(9, 15))
    assert not TradingCalendar().is_open(at(15, 30))


# ---------------------------------------------------------------- charges


def test_intraday_round_trip_matches_hand_calculation():
    c = round_trip(D("1000"), D("1010"), 100)
    # brokerage capped at Rs 20 per order; STT 0.025 % of the sell; stamp 0.003 % of the buy
    assert c.brokerage == D("40.00")
    assert c.stt == D("25.25")
    assert c.exchange == D("5.97")
    assert c.sebi == D("0.20")
    assert c.stamp == D("3.00")
    assert c.gst == D("8.31")
    assert c.total == D("82.73")


def test_small_order_pays_percentage_brokerage():
    c = round_trip(D("500"), D("505"), 10)
    assert c.brokerage == D("3.02")  # 0.03 % of 5,000 + 0.03 % of 5,050, under the cap


def test_cost_estimate_is_about_a_tenth_of_a_percent():
    assert D("0.10") < cost_pct_estimate("intraday") < D("0.11")
    assert cost_pct_estimate("delivery") > D("0.2")


# ---------------------------------------------------------------- Exit Planner


def test_orb_stop_at_range_midpoint_and_2r_target():
    wide = ExitParams(max_risk_pct=D("3"))  # 2.2 on 102.2 is 2.15 %, over the 2 % default
    assert "too wide" in plan_exit(orb_setup(), D("102.20"), pd.DataFrame()).reason
    p = plan_exit(orb_setup(), D("102.20"), pd.DataFrame(), wide)
    assert isinstance(p, ExitPlan)
    assert (p.stop, p.target, p.tick) == (D("100.00"), D("106.60"), D("0.01"))
    assert p.risk_per_share == D("2.20") and p.reward_risk == D("2.00")
    assert p.flat_by == "15:15" and p.stop_rule == "or_mid"


def test_rounding_is_conservative_on_the_tick_grid():
    s = orb_setup(price=1167.4, level=1170.3, hi=1170.3, lo=1160.15)
    p = plan_exit(s, D("1167.40"), pd.DataFrame(), instrument_tick=D("0.05"))
    assert p.stop == D("1165.20")  # 1165.225 rounded down (away from a buy's entry)
    assert p.target == D("1171.80")


def test_short_side_mirrors():
    s = orb_setup(side="sell", price=98.0, level=98.5, hi=101.55, lo=98.5)
    p = plan_exit(s, D("98.00"), pd.DataFrame(), ExitParams(max_risk_pct=D("3")), D("0.05"))
    assert p.stop == D("100.05")  # 100.025 rounded up (away from a sell's entry)
    assert p.target < p.entry


@pytest.mark.parametrize(
    "params, why",
    [
        (ExitParams(stop="pct:0.05"), "too tight"),
        (ExitParams(stop="pct:3"), "too wide"),
        (ExitParams(stop="pct:0.15", target_r=D("0.5")), "cannot pay"),
    ],
)
def test_refusals(params, why):
    r = plan_exit(orb_setup(price=1167.4), D("1167.40"), pd.DataFrame(), params)
    assert isinstance(r, Refused) and why in r.reason


def test_stop_on_the_wrong_side_is_refused():
    s = Setup("supertrend", "X", "buy", pd.Timestamp(at(10, 0)), 102.0, 105.0, "t", {})
    r = plan_exit(s, D("102.00"), pd.DataFrame())
    assert isinstance(r, Refused) and "wrong side" in r.reason


def test_atr_stop_uses_candles():
    df = pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [101.0] * 20,
            "low": [99.0] * 20,
            "close": [100.0] * 20,
            "volume": [1] * 20,
        }
    )
    s = Setup("ema_cross", "X", "buy", pd.Timestamp(at(10, 0)), 100.0, 99.0, "t", {})
    p = plan_exit(s, D("100.00"), df, ExitParams(max_risk_pct=D("5")))
    assert p.stop_rule == "atr:1.5" and p.stop == D("97.00")  # ATR 2 x 1.5


def test_orb_plan_needs_a_range():
    s = Setup("ema_cross", "X", "buy", pd.Timestamp(at(10, 0)), 100.0, 99.0, "t", {})
    assert isinstance(plan_exit(s, D("100"), pd.DataFrame(), ExitParams(stop="or_mid")), Refused)


# ---------------------------------------------------------------- Entry Timer


def test_entry_goes_on_a_fresh_closed_candle():
    d = decide_entry(hit(), at(10, 5, 20), D("102.25"))
    assert d.status == "go" and d.entry_price == D("102.25")
    assert d.trigger_key == "orb:SBIN:buy:2026-11-10"


@pytest.mark.parametrize(
    "now, ltp, why",
    [
        (at(10, 4, 50), D("102.2"), "not closed"),
        (at(10, 8), D("102.2"), "Too late"),
        (at(10, 5, 20), D("102.9"), "already ran"),
        (at(10, 5, 20), D("101.4"), "already failed"),
        (at(10, 5, 20), None, "No live price"),
    ],
)
def test_entry_real_market_guards(now, ltp, why):
    d = decide_entry(hit(), now, ltp)
    assert d.status == "skip" and why in d.reason


def test_entry_window_and_calendar():
    early = hit(orb_setup(bar=(9, 20)))
    assert "Before the entry window" in decide_entry(early, at(9, 25, 10), D("102.2")).reason
    late = hit(orb_setup(bar=(14, 30)))
    assert "After the entry window" in decide_entry(late, at(14, 35, 10), D("102.2")).reason
    holiday = TradingCalendar([DAY])
    assert (
        "Not a trading day"
        in decide_entry(hit(), at(10, 5, 10), D("102.2"), calendar=holiday).reason
    )


def test_entry_once_per_day_and_only_with_the_mood():
    h = hit()
    assert (
        "Already entered"
        in decide_entry(h, at(10, 5, 10), D("102.2"), already_triggered={trigger_key(h)}).reason
    )
    assert "Market mood" in decide_entry(hit(ok=False), at(10, 5, 10), D("102.2")).reason


def test_entry_delay_is_configurable_for_slower_feeds():
    p = EntryParams(max_delay=timedelta(minutes=4))
    assert decide_entry(hit(), at(10, 8), D("102.2"), params=p).status == "go"
