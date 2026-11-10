from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import login_limiter
from app.brokers.base import ConnectionReport, Funds
from app.brokers.dhan import DhanBroker
from app.core.db import get_session
from app.main import app
from app.models import BrokerCredential, EventLog

PW = "a-strong-password-1"
CLIENT = "1100001234"
TRADE_TOKEN = "eyJhbGciOiJIUzUxMiJ9.trading-token-part.SIGtradeAAAA1111"
DATA_TOKEN = "eyJhbGciOiJIUzUxMiJ9.data-token-part.SIGdataBBBB2222"


@pytest.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_session] = _session
    login_limiter.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def user(client: AsyncClient, email: str) -> dict[str, str]:
    r = await client.post("/auth/signup", json={"email": email, "password": PW})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def add(client: AsyncClient, h: dict, broker: str = "dhan", label: str = "Dhan main") -> dict:
    r = await client.post("/brokers", json={"broker": broker, "label": label}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def field(acct: dict, purpose: str, name: str) -> dict:
    return next(f for f in acct["credentials"][purpose]["fields"] if f["name"] == name)


async def test_available_brokers(client: AsyncClient) -> None:
    h = await user(client, "a@example.com")
    keys = {b["key"] for b in (await client.get("/brokers/available", headers=h)).json()}
    assert {"dhan", "paper"} <= keys


async def test_paper_broker_connects_without_keys(client: AsyncClient) -> None:
    h = await user(client, "p@example.com")
    acct = await add(client, h, "paper", "Practice")
    assert acct["is_paper"] and acct["status"] == "new"
    assert acct["credentials"]["trading"]["needs_credentials"] is False
    r = await client.post(f"/brokers/{acct['id']}/test", headers=h)
    body = r.json()
    assert body["ok"] is True
    assert Decimal(body["funds_available"]) == Decimal("100000")
    assert body["account"]["status"] == "connected"


async def test_keys_saved_encrypted_and_only_last4_returned(
    client: AsyncClient, db: AsyncSession
) -> None:
    h = await user(client, "k@example.com")
    acct = await add(client, h)
    r = await client.put(
        f"/brokers/{acct['id']}/credentials/trading",
        json={"fields": {"client_id": CLIENT, "access_token": TRADE_TOKEN}},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert TRADE_TOKEN not in r.text
    out = r.json()
    tok = field(out, "trading", "access_token")
    assert tok["saved"] and tok["last4"] == TRADE_TOKEN[-4:] and tok["value"] is None
    cid = field(out, "trading", "client_id")
    assert cid["value"] == CLIENT  # not a secret, shown in full
    assert out["credentials"]["trading"]["complete"] is True
    assert out["credentials"]["data"]["complete"] is False

    raw = (await db.execute(text("SELECT value_enc FROM broker_credentials"))).scalars().all()
    assert raw and all(TRADE_TOKEN.encode() not in bytes(v) for v in raw)

    listed = await client.get("/brokers", headers=h)
    assert TRADE_TOKEN not in listed.text


async def test_data_key_added_later_does_not_touch_trading_key(
    client: AsyncClient, db: AsyncSession
) -> None:
    h = await user(client, "later@example.com")
    acct = await add(client, h)
    url = f"/brokers/{acct['id']}/credentials"
    await client.put(
        f"{url}/trading",
        json={"fields": {"client_id": CLIENT, "access_token": TRADE_TOKEN}},
        headers=h,
    )
    before = (
        await db.execute(
            select(BrokerCredential.field, BrokerCredential.value_enc, BrokerCredential.updated_at)
            .where(BrokerCredential.purpose == "trading")
            .order_by(BrokerCredential.field)
        )
    ).all()

    r = await client.put(
        f"{url}/data", json={"fields": {"client_id": CLIENT, "access_token": DATA_TOKEN}}, headers=h
    )
    assert r.json()["credentials"]["data"]["complete"] is True

    db.expire_all()
    after = (
        await db.execute(
            select(BrokerCredential.field, BrokerCredential.value_enc, BrokerCredential.updated_at)
            .where(BrokerCredential.purpose == "trading")
            .order_by(BrokerCredential.field)
        )
    ).all()
    assert [tuple(x) for x in before] == [tuple(x) for x in after]


async def test_partial_update_keeps_other_fields(client: AsyncClient) -> None:
    h = await user(client, "daily@example.com")
    acct = await add(client, h)
    url = f"/brokers/{acct['id']}/credentials/trading"
    await client.put(
        url, json={"fields": {"client_id": CLIENT, "access_token": TRADE_TOKEN}}, headers=h
    )
    new_token = "eyJ.new-daily-token.ZZZZ9999"
    r = await client.put(url, json={"fields": {"access_token": new_token}}, headers=h)
    out = r.json()
    assert field(out, "trading", "client_id")["value"] == CLIENT
    assert field(out, "trading", "access_token")["last4"] == "9999"


@pytest.mark.parametrize(
    "fields",
    [{"password": "x" * 10}, {"access_token": "   "}, {}],
)
async def test_bad_credentials_rejected(client: AsyncClient, fields: dict) -> None:
    h = await user(client, "bad@example.com")
    acct = await add(client, h)
    r = await client.put(
        f"/brokers/{acct['id']}/credentials/trading", json={"fields": fields}, headers=h
    )
    assert r.status_code == 422


async def test_paper_has_no_keys_to_save(client: AsyncClient) -> None:
    h = await user(client, "pk@example.com")
    acct = await add(client, h, "paper", "Paper")
    r = await client.put(
        f"/brokers/{acct['id']}/credentials/trading", json={"fields": {"x": "y"}}, headers=h
    )
    assert r.status_code == 422


async def test_unknown_broker_and_duplicate_label(client: AsyncClient) -> None:
    h = await user(client, "dup@example.com")
    r = await client.post("/brokers", json={"broker": "nope", "label": "X"}, headers=h)
    assert r.status_code == 422
    await add(client, h, "dhan", "Main")
    r = await client.post("/brokers", json={"broker": "paper", "label": "Main"}, headers=h)
    assert r.status_code == 409


async def test_connection_ok_sets_connected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    expires = datetime.now(UTC) + timedelta(hours=20)

    async def fake_test(self: DhanBroker) -> ConnectionReport:
        assert self.credentials.trading["access_token"] == TRADE_TOKEN  # decrypted correctly
        return ConnectionReport(
            ok=True,
            message="Connected to Dhan",
            purpose_ok={"trading": True},
            funds=Funds(available=Decimal("5000.50")),
            token_expires_at=expires,
        )

    monkeypatch.setattr(DhanBroker, "test_connection", fake_test)
    h = await user(client, "ok@example.com")
    acct = await add(client, h)
    await client.put(
        f"/brokers/{acct['id']}/credentials/trading",
        json={"fields": {"client_id": CLIENT, "access_token": TRADE_TOKEN}},
        headers=h,
    )
    body = (await client.post(f"/brokers/{acct['id']}/test", headers=h)).json()
    assert body["ok"] and body["account"]["status"] == "connected"
    assert Decimal(body["funds_available"]) == Decimal("5000.50")
    assert body["account"]["token_expires_at"] is not None


async def test_connection_error_message_is_masked(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def leaky_test(self: DhanBroker) -> ConnectionReport:
        # Even if an adapter put the token in its message, it must never be stored or returned.
        return ConnectionReport(ok=False, message=f"auth failed for token {TRADE_TOKEN}")

    monkeypatch.setattr(DhanBroker, "test_connection", leaky_test)
    h = await user(client, "leak@example.com")
    acct = await add(client, h)
    await client.put(
        f"/brokers/{acct['id']}/credentials/trading",
        json={"fields": {"client_id": CLIENT, "access_token": TRADE_TOKEN}},
        headers=h,
    )
    r = await client.post(f"/brokers/{acct['id']}/test", headers=h)
    assert r.json()["ok"] is False
    assert r.json()["account"]["status"] == "error"
    assert TRADE_TOKEN not in r.text
    stored = await db.scalar(text("SELECT last_error FROM broker_accounts"))
    assert stored is not None and TRADE_TOKEN not in stored
    payloads = " ".join(
        str(e.payload) + e.message for e in (await db.scalars(select(EventLog))).all()
    )
    assert TRADE_TOKEN not in payloads


async def test_remove_purpose_and_disconnect(client: AsyncClient, db: AsyncSession) -> None:
    h = await user(client, "dc@example.com")
    acct = await add(client, h)
    url = f"/brokers/{acct['id']}"
    for purpose, tok in (("trading", TRADE_TOKEN), ("data", DATA_TOKEN)):
        await client.put(
            f"{url}/credentials/{purpose}",
            json={"fields": {"client_id": CLIENT, "access_token": tok}},
            headers=h,
        )
    r = await client.delete(f"{url}/credentials/data", headers=h)
    assert r.json()["credentials"]["data"]["complete"] is False
    assert r.json()["credentials"]["trading"]["complete"] is True

    assert (await client.delete(url, headers=h)).status_code == 204
    assert (await client.get(url, headers=h)).status_code == 404
    assert await db.scalar(select(func.count()).select_from(BrokerCredential)) == 0


async def test_users_cannot_touch_each_others_brokers(client: AsyncClient) -> None:
    a = await user(client, "alice@example.com")
    b = await user(client, "bob@example.com")
    acct = await add(client, a)
    url = f"/brokers/{acct['id']}"

    assert (await client.get("/brokers", headers=b)).json() == []
    assert (await client.get(url, headers=b)).status_code == 404
    r = await client.put(
        f"{url}/credentials/trading", json={"fields": {"access_token": "steal"}}, headers=b
    )
    assert r.status_code == 404
    assert (await client.post(f"{url}/test", headers=b)).status_code == 404
    assert (await client.delete(f"{url}/credentials/trading", headers=b)).status_code == 404
    assert (await client.delete(url, headers=b)).status_code == 404
    assert (await client.get(url, headers=a)).status_code == 200


async def test_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/brokers")).status_code == 401
