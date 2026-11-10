"""Strategy builder ("Build from scratch"): user-made rules, checked on closed candles only."""

from collections.abc import AsyncIterator

import fakeredis
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import login_limiter
from app.core.db import get_session
from app.core.redis import set_redis
from app.engine.builder import evaluate, scan_builder, series
from app.engine.setups import ist_dates
from app.main import app
from app.schemas.strategy import BuilderSpec, StrategyCreate
from tests.test_paper_trading import BULL, at, make_user, orb_day, run_chain

PW = "a-strong-password-1"


def frame(closes, start=(9, 15), volume=1000, step=5):
    h, m = start
    rows = []
    for i, c in enumerate(closes):
        mins = h * 60 + m + i * step
        rows.append(
            {
                "ts": pd.Timestamp(at(mins // 60, mins % 60)),
                "open": c - 0.5,
                "high": c + 1,
                "low": c - 1,
                "close": float(c),
                "volume": volume if not isinstance(volume, list) else volume[i],
            }
        )
    return pd.DataFrame(rows)


def cond(left, op, right):
    return {"left": left, "op": op, "right": right}


CLOSE = {"kind": "close"}
NUM = lambda v: {"kind": "number", "value": v}  # noqa: E731


# ---------------------------------------------------------------- evaluation


def test_crosses_above_needs_the_cross_on_the_last_candle():
    g = {"match": "all", "conditions": [cond(CLOSE, "crosses_above", NUM(100))]}
    assert evaluate(frame([98, 99, 101]), g)[0]
    assert not evaluate(frame([98, 101, 102]), g)[0]  # crossed one candle ago, not now
    assert not evaluate(frame([98, 99, 99.5]), g)[0]


def test_above_below_and_any_all():
    above = cond(CLOSE, "above", NUM(100))
    below = cond(CLOSE, "below", NUM(50))
    df = frame([101, 102])
    assert evaluate(df, {"match": "all", "conditions": [above]})[0]
    assert not evaluate(df, {"match": "all", "conditions": [above, below]})[0]
    assert evaluate(df, {"match": "any", "conditions": [above, below]})[0]


def test_indicators_wait_for_enough_candles():
    g = {"match": "all", "conditions": [cond(CLOSE, "above", {"kind": "sma", "period": 5})]}
    ok, [r] = evaluate(frame([100, 101, 102]), g)
    assert not ok and "not enough data" in r.text


def test_volume_multiple_uses_earlier_candles_only():
    vols = [100] * 20 + [400]
    df = frame([100] * 21, volume=vols, step=1)
    g = {
        "match": "all",
        "conditions": [
            cond({"kind": "volume"}, "above", {"kind": "avg_volume", "period": 20, "mult": 1.5})
        ],
    }
    ok, [r] = evaluate(df, g)
    assert ok and "1.5× Average volume(20)" in r.text


def test_today_high_so_far_excludes_the_current_candle():
    df = frame([100, 102, 105])
    s = series(df, {"kind": "day_high"}, ist_dates(df))
    assert s.iloc[-1] == 103  # high of the earlier candles (102 + 1), not this one's 106


def test_opening_range_is_unknown_until_09_30():
    df = frame([100, 101, 102, 104])  # 09:15, 09:20, 09:25, 09:30
    s = series(df, {"kind": "or_high"}, ist_dates(df))
    assert s.iloc[:3].isna().all() and s.iloc[-1] == 103


def test_no_look_ahead():
    g = {"match": "all", "conditions": [cond(CLOSE, "crosses_above", {"kind": "ema", "period": 3})]}
    df = frame([100, 99, 98, 97, 101, 90, 80])
    full = evaluate(df.iloc[:5], g)[0]
    assert evaluate(df.iloc[:5].copy(), g)[0] == full  # adding later rows cannot change the past
    assert full


def test_scan_builder_makes_setups_with_the_crossed_level():
    spec = {
        "mood": "trend",
        "buy": {"conditions": [cond(CLOSE, "crosses_above", {"kind": "or_high"})]},
        "sell": None,
    }
    df = frame([100, 101, 102, 105])  # range high 103; the 09:30 close 105 crosses it
    [hit] = scan_builder("SBIN", df, None, spec)
    assert hit.setup.rule == "custom" and hit.setup.side == "buy"
    assert hit.setup.level == 103 and hit.setup.data == {"or_high": 103.0, "or_low": 99.0}
    assert not hit.mood.ok  # no market mood yet: the filter still applies

    off = scan_builder("SBIN", df, None, {**spec, "mood": "off"})
    assert off[0].mood.ok


# ---------------------------------------------------------------- validation


def test_spec_validation():
    good = {"buy": {"conditions": [cond(CLOSE, "crosses_above", {"kind": "vwap"})]}}
    spec = BuilderSpec.model_validate(good)
    assert spec.buy.conditions[0].right.period is None
    ema = BuilderSpec.model_validate(
        {"sell": {"conditions": [cond(CLOSE, "below", {"kind": "ema"})]}}
    )
    assert ema.sell.conditions[0].right.period == 20  # default filled in
    bad = [
        {},  # no side
        {"buy": {"conditions": []}},
        {"buy": {"conditions": [cond(NUM(1), "above", CLOSE)]}},  # number on the left
        {"buy": {"conditions": [cond(CLOSE, "above", CLOSE)]}},  # same thing twice
        {"buy": {"conditions": [cond(CLOSE, "above", {"kind": "number"})]}},  # no value
        {"buy": {"conditions": [cond(CLOSE, "above", {"kind": "rsi", "period": 500})]}},
        {"buy": {"conditions": [cond(CLOSE, "above", {"kind": "magic"})]}},
        {"buy": {"conditions": [cond(CLOSE, "nearly", NUM(1))]}},
        {"buy": {"conditions": [cond(CLOSE, "above", NUM(1))] * 9}},
    ]
    for b in bad:
        with pytest.raises(ValidationError):
            BuilderSpec.model_validate(b)


def test_create_needs_template_or_rules_not_both():
    rules = {"buy": {"conditions": [cond(CLOSE, "above", NUM(1))]}}
    StrategyCreate.model_validate({"name": "Mine", "params": {"builder": rules}})
    StrategyCreate.model_validate({"name": "ORB", "template_key": "orb"})
    for body in (
        {"name": "x"},
        {"name": "x", "template_key": "orb", "params": {"builder": rules}},
    ):
        with pytest.raises(ValidationError):
            StrategyCreate.model_validate(body)


# ---------------------------------------------------------------- through the agents


async def test_builder_strategy_runs_through_the_whole_chain(db: AsyncSession):
    from sqlalchemy import select

    from app.models import Strategy, Trade

    user = await make_user(db)
    db.add(
        Strategy(
            user_id=user.id,
            name="My breakout",
            section="intraday",
            kind="builder",
            template_key=None,
            status="paper",
            params={
                "timeframe": "5m",
                "symbols": ["SBIN"],
                "mode": "auto",
                "builder": {
                    "mood": "trend",
                    "buy": {
                        "match": "all",
                        "conditions": [cond(CLOSE, "crosses_above", {"kind": "or_high"})],
                    },
                },
            },
        )
    )
    await db.flush()
    await orb_day(db)  # 09:15-09:25 range high 822.00; the 09:30 candle closes at 823.50

    [sig] = await run_chain(db, ctx=BULL)
    assert sig.rule == "custom" and sig.side == "buy", sig.status_reason
    assert "Close crossed above Opening range high" in sig.reason
    assert sig.status == "taken", sig.status_reason
    assert sig.plan["stop_rule"].startswith("atr")  # custom rules default to an ATR stop
    trade = await db.scalar(select(Trade).where(Trade.user_id == user.id))
    assert trade is not None and trade.status == "open"
    assert await run_chain(db, ctx=BULL) == []  # once per setup per day


# ---------------------------------------------------------------- API


@pytest.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    set_redis(fakeredis.FakeAsyncRedis(decode_responses=True))

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_session] = _session
    login_limiter.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    set_redis(None)


async def test_api_create_builder_strategy(client):
    r = await client.post("/auth/signup", json={"email": "a@example.com", "password": PW})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    opts = (await client.get("/strategies/builder", headers=h)).json()
    assert {"close", "vwap", "or_high", "number"} <= {o["kind"] for o in opts["operands"]}

    rules = {"buy": {"conditions": [cond(CLOSE, "crosses_above", {"kind": "vwap"})]}}
    r = await client.post(
        "/strategies",
        headers=h,
        json={"name": "VWAP mine", "section": "intraday", "params": {"builder": rules}},
    )
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["kind"] == "builder" and s["template_key"] is None
    assert s["params"]["builder"]["buy"]["conditions"][0]["right"]["kind"] == "vwap"

    # Mode changes keep the rules; a template strategy cannot sneak rules in.
    r = await client.patch(
        f"/strategies/{s['id']}", headers=h, json={"params": {**s["params"], "mode": "auto"}}
    )
    assert r.status_code == 200 and r.json()["params"]["builder"] is not None
    t = (
        await client.post("/strategies", headers=h, json={"name": "ORB", "template_key": "orb"})
    ).json()
    r = await client.patch(f"/strategies/{t['id']}", headers=h, json={"params": {"builder": rules}})
    assert r.status_code == 422
