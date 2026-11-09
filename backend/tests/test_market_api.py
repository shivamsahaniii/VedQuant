import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from app.api.auth import login_limiter
from app.core.redis import set_redis
from app.data.feed import QUOTES_KEY, TICKS_CHANNEL
from app.main import app
from app.models import Candle

PW = "a-strong-password-1"


def quote(symbol: str, ltp: str) -> dict:
    return {
        "exchange": "NSE",
        "symbol": symbol,
        "ltp": ltp,
        "open": ltp,
        "high": ltp,
        "low": ltp,
        "change": "0",
        "change_pct": "0.00",
        "volume": 10,
        "ts": datetime.now(UTC).isoformat(),
    }


@pytest.fixture
def server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def client(db: AsyncSession, server: fakeredis.FakeServer) -> Iterator[TestClient]:
    set_redis(fakeredis.FakeAsyncRedis(server=server, decode_responses=True))
    login_limiter.clear()
    with TestClient(app) as c:
        yield c
    set_redis(None)


@pytest.fixture
def writer(server: fakeredis.FakeServer) -> fakeredis.FakeRedis:
    """Plays the feed service: writes quotes and publishes ticks."""
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def token(client: TestClient, email: str = "m@example.com") -> str:
    r = client.post("/auth/signup", json={"email": email, "password": PW})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def test_quotes_snapshot_index_first(client: TestClient, writer: fakeredis.FakeRedis) -> None:
    writer.hset(QUOTES_KEY, "NSE:SBIN", json.dumps(quote("SBIN", "800")))
    writer.hset(QUOTES_KEY, "NSE:NIFTY50", json.dumps(quote("NIFTY50", "24000")))
    writer.hset(QUOTES_KEY, "NSE:INFY", json.dumps(quote("INFY", "1800")))
    h = {"Authorization": f"Bearer {token(client)}"}
    symbols = [q["symbol"] for q in client.get("/market/quotes", headers=h).json()]
    assert symbols == ["NIFTY50", "INFY", "SBIN"]
    assert client.get("/market/quotes").status_code == 401


async def test_candles_endpoint(client: TestClient, db: AsyncSession) -> None:
    t0 = datetime(2026, 11, 9, 3, 45, tzinfo=UTC)
    for i in range(5):
        db.add(
            Candle(
                exchange="NSE",
                symbol="SBIN",
                timeframe="1m",
                ts=t0 + timedelta(minutes=i),
                open=Decimal(800 + i),
                high=Decimal(801 + i),
                low=Decimal(799 + i),
                close=Decimal(800 + i),
                volume=100,
            )
        )
    await db.commit()
    h = {"Authorization": f"Bearer {token(client, 'c@example.com')}"}
    rows = client.get("/market/candles?symbol=sbin&timeframe=1m&limit=3", headers=h).json()
    assert [Decimal(r["close"]) for r in rows] == [Decimal(802), Decimal(803), Decimal(804)]


def test_ws_rejects_without_valid_token(client: TestClient) -> None:
    with client.websocket_connect("/ws/quotes") as ws:
        ws.send_json({"type": "auth", "token": "garbage"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1008


def test_ws_snapshot_then_live_quotes(client: TestClient, writer: fakeredis.FakeRedis) -> None:
    writer.hset(QUOTES_KEY, "NSE:SBIN", json.dumps(quote("SBIN", "800")))
    tok = token(client, "ws@example.com")
    with client.websocket_connect("/ws/quotes") as ws:
        ws.send_json({"type": "auth", "token": tok})
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["quotes"][0]["ltp"] == "800"
        writer.publish(TICKS_CHANNEL, json.dumps(quote("SBIN", "801.05")))
        msg = ws.receive_json()
        assert msg == {
            "type": "quote",
            "quote": quote("SBIN", "801.05") | {"ts": msg["quote"]["ts"]},
        }


def test_context_endpoint_and_ws_push(client: TestClient, writer: fakeredis.FakeRedis) -> None:
    from app.engine.worker import CONTEXT_CHANNEL, CONTEXT_KEY

    tok = token(client, "ctx@example.com")
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/market/context", headers=h).json() is None
    writer.set(CONTEXT_KEY, json.dumps({"summary": "Uptrend · strong", "bias": "bullish"}))
    assert client.get("/market/context", headers=h).json()["bias"] == "bullish"
    with client.websocket_connect("/ws/quotes") as ws:
        ws.send_json({"type": "auth", "token": tok})
        assert ws.receive_json()["context"]["summary"] == "Uptrend · strong"
        writer.publish(CONTEXT_CHANNEL, json.dumps({"summary": "Sideways", "bias": "neutral"}))
        msg = ws.receive_json()
        assert msg == {"type": "context", "context": {"summary": "Sideways", "bias": "neutral"}}
