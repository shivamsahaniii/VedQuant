"""Trading API: signals, positions, journal, manual close, kill switch, status changes,
and that one user can never see or touch another user's trades."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal as D

import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import login_limiter
from app.core.db import get_session
from app.core.redis import set_redis
from app.data.feed import QUOTES_KEY
from app.main import app
from app.models import Signal, Strategy, Trade, User
from app.orders.paper import OpenRequest, open_trade

PW = "a-strong-password-1"


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.FakeAsyncRedis]:
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    set_redis(r)
    yield r
    set_redis(None)


@pytest.fixture
async def client(db: AsyncSession, redis) -> AsyncIterator[AsyncClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_session] = _session
    login_limiter.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def signup(client, email) -> tuple[dict[str, str], uuid.UUID]:
    r = await client.post("/auth/signup", json={"email": email, "password": PW})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await client.get("/auth/me", headers=h)).json()
    return h, uuid.UUID(me["id"])


async def a_trade(db, user_id, symbol="TCS", section="intraday"):
    t = await open_trade(
        db,
        OpenRequest(
            user_id=user_id,
            strategy_id=None,
            signal_id=None,
            section=section,
            exchange="NSE",
            symbol=symbol,
            side="buy",
            qty=10,
            stop=D("990"),
            target=D("1020"),
            ref=f"t:{uuid.uuid4()}",
            tick=D("0.05"),
        ),
        D("1000"),
        datetime.now(UTC),
    )
    await db.commit()
    return t


async def price(redis, symbol, ltp):
    await redis.hset(
        QUOTES_KEY, f"NSE:{symbol}", json.dumps({"exchange": "NSE", "symbol": symbol, "ltp": ltp})
    )


async def test_positions_and_summary(client, db, redis):
    h, me = await signup(client, "a@example.com")
    await a_trade(db, me)
    await price(redis, "TCS", "1010")
    [t] = (await client.get("/trades?status=open", headers=h)).json()
    assert D(t["unrealised"]) == D("95")  # (1010 - 1000.50) x 10
    s = (await client.get("/trading/summary", headers=h)).json()
    assert s["open_positions"] == 1 and D(s["unrealised"]) == D("95") and s["win_rate"] is None


async def test_manual_close_and_journal(client, db, redis):
    h, me = await signup(client, "a@example.com")
    t = await a_trade(db, me)
    await price(redis, "TCS", "1015")
    r = await client.post(f"/trades/{t.id}/close", headers=h)
    assert r.status_code == 200 and r.json()["exit_reason"] == "manual"
    assert (await client.post(f"/trades/{t.id}/close", headers=h)).status_code == 409
    s = (await client.get("/trading/summary", headers=h)).json()
    assert s["closed_trades"] == 1 and s["win_rate"] == 100.0
    assert s["per_strategy"][0]["strategy"] == "Manual"


async def test_users_are_isolated(client, db, redis):
    ha, a = await signup(client, "a@example.com")
    hb, _ = await signup(client, "b@example.com")
    t = await a_trade(db, a)
    await price(redis, "TCS", "1010")
    assert (await client.get("/trades", headers=hb)).json() == []
    assert (await client.post(f"/trades/{t.id}/close", headers=hb)).status_code == 404
    assert (await client.post("/trading/kill-switch", headers=hb)).json()["closed"] == 0
    assert (await db.get(Trade, t.id)).status == "open"


async def test_kill_switch_closes_everything_and_pauses(client, db, redis):
    h, me = await signup(client, "a@example.com")
    await a_trade(db, me, "TCS")
    await a_trade(db, me, "SBIN", section="swing")
    await price(redis, "TCS", "1001")
    await price(redis, "SBIN", "999")
    s = Strategy(user_id=me, name="ORB", section="intraday", template_key="orb", status="paper")
    db.add(s)
    await db.commit()
    r = (await client.post("/trading/kill-switch", headers=h)).json()
    assert r == {"closed": 2, "paused": 1}
    await db.refresh(s)
    assert s.status == "paused"
    reasons = set((await db.scalars(select(Trade.exit_reason))).all())
    assert reasons == {"kill_switch"}


async def test_start_and_pause_paper_trading(client):
    h, _ = await signup(client, "a@example.com")
    lib = (
        await client.post("/strategies", headers=h, json={"name": "Lib", "template_key": "orb"})
    ).json()
    r = await client.post(f"/strategies/{lib['id']}/status", headers=h, json={"status": "paper"})
    assert r.status_code == 409 and "section" in r.json()["detail"]
    s = (
        await client.post(
            "/strategies",
            headers=h,
            json={
                "name": "ORB",
                "template_key": "orb",
                "section": "intraday",
                "params": {"mode": "auto", "target_r": "1.5"},
            },
        )
    ).json()
    assert s["params"]["mode"] == "auto" and s["params"]["stop_rule"] == "auto"
    r = await client.post(f"/strategies/{s['id']}/status", headers=h, json={"status": "paper"})
    assert r.json()["status"] == "paper"
    r = await client.post(f"/strategies/{s['id']}/status", headers=h, json={"status": "live"})
    assert r.status_code == 422  # live is Phase 4: not even accepted
    r = await client.post(f"/strategies/{s['id']}/status", headers=h, json={"status": "paused"})
    assert r.json()["status"] == "paused"


async def test_signals_list_is_per_user(client, db):
    ha, a = await signup(client, "a@example.com")
    hb, b = await signup(client, "b@example.com")
    s = Strategy(user_id=a, name="ORB", section="intraday", template_key="orb", status="paper")
    db.add(s)
    await db.flush()
    db.add(
        Signal(
            user_id=a,
            strategy_id=s.id,
            section="intraday",
            exchange="NSE",
            symbol="SBIN",
            side="buy",
            rule="orb",
            trigger_key="orb:SBIN:buy:2026-11-10",
            bar_ts=datetime.now(UTC),
            price=D("823.5"),
            reason="r",
            status="suggested",
            status_reason="",
            mood={},
        )
    )
    await db.commit()
    [sig] = (await client.get("/signals", headers=ha)).json()
    assert sig["strategy"] == "ORB" and sig["status"] == "suggested"
    assert (await client.get("/signals", headers=hb)).json() == []
    assert b != a and await db.scalar(select(User.id).where(User.id == b))
