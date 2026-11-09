"""Connections catalog + preferences, and the Markets lists (indices, stocks, crypto)."""

import json
import uuid
from collections.abc import AsyncIterator

import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import login_limiter
from app.api.connections import request_counts
from app.connectors.catalog import CONNECTORS
from app.core.db import get_session
from app.core.redis import set_redis
from app.data.feed import QUOTES_KEY
from app.main import app
from app.markets.catalog import CATALOG, DEFAULTS
from app.models import BrokerAccount

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


async def signup(client, email="a@example.com"):
    r = await client.post("/auth/signup", json={"email": email, "password": PW})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await client.get("/auth/me", headers=h)).json()["id"]


def test_catalog_is_consistent():
    keys = [c.key for c in CONNECTORS]
    assert len(keys) == len(set(keys))
    for c in CONNECTORS:
        if c.status == "available" and "trading" in c.provides:
            assert c.broker_key  # a real adapter behind every connectable broker
    assert {m.asset_class for m in CATALOG} == {"indices", "stocks", "crypto"}


async def test_connectors_list_and_defaults(client):
    h, _ = await signup(client)
    r = (await client.get("/connectors", headers=h)).json()
    by = {c["key"]: c for c in r["connectors"]}
    assert by["paper"]["status"] == "available" and by["paper"]["in_use_for"] == [
        "indices",
        "stocks",
    ]
    assert by["vedquant_charts"]["in_use_for"] == ["charts"]
    assert by["angelone"]["status"] == "coming_soon"
    assert r["preferences"]["data_sources"]["crypto"] is None


async def test_preferences_validate_choices(client, db):
    h, uid = await signup(client)
    ok = await client.put(
        "/connectors/preferences", headers=h, json={"chart_provider": "tradingview_widget"}
    )
    assert ok.status_code == 200 and ok.json()["chart_provider"] == "tradingview_widget"
    bad = [
        ({"chart_provider": "dhan"}, 422),
        ({"chart_provider": "tradingview_advanced"}, 409),  # coming soon
        ({"data_sources": {"crypto": "dhan"}}, 422),  # Dhan has no crypto
        ({"data_sources": {"crypto": "binance"}}, 409),  # not built yet
        ({"data_sources": {"stocks": "dhan"}}, 409),  # no connected Dhan account
    ]
    for body, code in bad:
        assert (
            await client.put("/connectors/preferences", headers=h, json=body)
        ).status_code == code, body
    db.add(BrokerAccount(user_id=uuid.UUID(uid), broker="dhan", label="Main", status="connected"))
    await db.commit()
    r = await client.put(
        "/connectors/preferences", headers=h, json={"data_sources": {"stocks": "dhan"}}
    )
    assert r.status_code == 200 and r.json()["data_sources"]["stocks"] == "dhan"


async def test_request_a_coming_soon_connector(client, db):
    h, _ = await signup(client)
    hb, _ = await signup(client, "b@example.com")
    assert (await client.post("/connectors/angelone/request", headers=h)).json()["requested"]
    await client.post("/connectors/angelone/request", headers=h)  # twice counts once
    await client.post("/connectors/angelone/request", headers=hb)
    assert (await client.post("/connectors/dhan/request", headers=h)).status_code == 409
    assert (await client.post("/connectors/nope/request", headers=h)).status_code == 404
    assert (await request_counts(db))["angelone"] == 2
    by = {c["key"]: c for c in (await client.get("/connectors", headers=h)).json()["connectors"]}
    assert by["angelone"]["requested"] is True


async def test_watchlist_seeds_defaults_with_data_status(client, redis):
    h, _ = await signup(client)
    await redis.hset(
        QUOTES_KEY, "NSE:SBIN", json.dumps({"exchange": "NSE", "symbol": "SBIN", "ltp": "820"})
    )
    items = (await client.get("/markets/watchlist", headers=h)).json()["items"]
    assert len(items) == len(DEFAULTS)
    by = {i["symbol"]: i for i in items}
    assert by["SBIN"]["data"]["state"] == "live" and by["SBIN"]["quote"]["ltp"] == "820"
    assert by["BANKNIFTY"]["data"]["state"] == "unsupported"  # simulator doesn't cover it
    assert (
        by["BTCUSDT"]["data"]["state"] == "no_source" and by["BTCUSDT"]["tv"] == "BINANCE:BTCUSDT"
    )
    assert by["NIFTY50"]["tv"] == "NSE:NIFTY"


async def test_add_remove_and_validation(client):
    h, _ = await signup(client)
    r = await client.post(
        "/markets/watchlist",
        headers=h,
        json={"asset_class": "stocks", "exchange": "nse", "symbol": "tatasteel"},
    )
    assert r.status_code == 201
    dup = await client.post(
        "/markets/watchlist",
        headers=h,
        json={"asset_class": "stocks", "exchange": "NSE", "symbol": "TATASTEEL"},
    )
    assert dup.status_code == 409
    for body in (
        {"asset_class": "crypto", "exchange": "NSE", "symbol": "BTC"},
        {"asset_class": "stocks", "exchange": "NSE", "symbol": "BAD SYMBOL"},
    ):
        assert (await client.post("/markets/watchlist", headers=h, json=body)).status_code == 422
    items = (await client.get("/markets/watchlist", headers=h)).json()["items"]
    tata = next(i for i in items if i["symbol"] == "TATASTEEL")
    assert tata["tv"] == "NSE:TATASTEEL" and tata["name"] == "TATASTEEL"
    assert (await client.delete(f"/markets/watchlist/{tata['id']}", headers=h)).status_code == 204
    # Removing everything does not bring the defaults back.
    for i in (await client.get("/markets/watchlist", headers=h)).json()["items"]:
        await client.delete(f"/markets/watchlist/{i['id']}", headers=h)
    assert (await client.get("/markets/watchlist", headers=h)).json()["items"] == []


async def test_watchlists_are_per_user(client):
    ha, _ = await signup(client)
    hb, _ = await signup(client, "b@example.com")
    a_items = (await client.get("/markets/watchlist", headers=ha)).json()["items"]
    await client.get("/markets/watchlist", headers=hb)
    assert (
        await client.delete(f"/markets/watchlist/{a_items[0]['id']}", headers=hb)
    ).status_code == 404
    cat = (await client.get("/markets/catalog?asset=crypto", headers=ha)).json()["items"]
    assert all(i["asset_class"] == "crypto" for i in cat)
    assert {i["symbol"] for i in cat if i["followed"]} == {"BTCUSDT", "ETHUSDT"}
