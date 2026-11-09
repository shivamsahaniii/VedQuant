from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import login_limiter
from app.api.deps import AdminUser, CurrentUser, DbSession, owned_by
from app.core.db import get_session
from app.core.security import create_access_token
from app.main import app
from app.models import BrokerAccount, EventLog, PlatformSetting, User

PW = "a-strong-password-1"


# A tiny admin-only route, just for testing the role check.
@app.get("/_test/admin-only")
async def _admin_only(user: AdminUser) -> dict[str, str]:
    return {"ok": user.email}


# A tiny user-scoped route, just for testing per-user isolation.
@app.get("/_test/my-brokers")
async def _my_brokers(user: CurrentUser, db: DbSession) -> list[str]:
    rows = (await db.scalars(owned_by(BrokerAccount, user))).all()
    return [r.label for r in rows]


@pytest.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_session] = _session
    login_limiter.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def signup(client: AsyncClient, email: str = "user@example.com") -> str:
    r = await client.post("/auth/signup", json={"email": email, "password": PW})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_signup_returns_token_and_me_works(client: AsyncClient) -> None:
    token = await signup(client, "  New.User@Example.COM ")
    r = await client.get("/auth/me", headers=bearer(token))
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == "new.user@example.com"
    assert me["role"] == "user"
    assert me["trading_mode"] == "paper"
    assert "password_hash" not in me


async def test_password_hash_never_plain(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client)
    stored = await db.scalar(select(User.password_hash))
    assert stored is not None and PW not in stored


async def test_duplicate_signup_rejected(client: AsyncClient) -> None:
    await signup(client, "dup@example.com")
    r = await client.post("/auth/signup", json={"email": "DUP@example.com", "password": PW})
    assert r.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": PW},
        {"email": "x@example.com", "password": "short"},
        {"email": "x@example.com"},
    ],
)
async def test_signup_validation(client: AsyncClient, body: dict) -> None:
    r = await client.post("/auth/signup", json=body)
    assert r.status_code == 422


async def test_signups_can_be_closed(client: AsyncClient, db: AsyncSession) -> None:
    setting = await db.get(PlatformSetting, "signups_open")
    assert setting is not None
    setting.value = False
    await db.commit()
    try:
        r = await client.post("/auth/signup", json={"email": "late@example.com", "password": PW})
        assert r.status_code == 403
    finally:
        setting.value = True
        await db.commit()


async def test_login_good_and_bad_password(client: AsyncClient) -> None:
    await signup(client, "login@example.com")
    ok = await client.post("/auth/login", json={"email": "LOGIN@example.com", "password": PW})
    assert ok.status_code == 200
    assert ok.json()["token_type"] == "bearer"

    bad = await client.post("/auth/login", json={"email": "login@example.com", "password": "nope"})
    assert bad.status_code == 401
    unknown = await client.post("/auth/login", json={"email": "nobody@example.com", "password": PW})
    assert unknown.status_code == 401
    assert bad.json() == unknown.json()  # same message: doesn't reveal which emails exist


async def test_login_rate_limited_after_5_failures(client: AsyncClient) -> None:
    await signup(client, "brute@example.com")
    for _ in range(5):
        r = await client.post("/auth/login", json={"email": "brute@example.com", "password": "x"})
        assert r.status_code == 401
    r = await client.post("/auth/login", json={"email": "brute@example.com", "password": PW})
    assert r.status_code == 429


async def test_disabled_user_blocked(client: AsyncClient, db: AsyncSession) -> None:
    token = await signup(client, "off@example.com")
    await db.execute(text("UPDATE users SET is_active = false"))
    await db.commit()
    db.expire_all()
    assert (await client.get("/auth/me", headers=bearer(token))).status_code == 401
    r = await client.post("/auth/login", json={"email": "off@example.com", "password": PW})
    assert r.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer garbage"}, {"Authorization": "Basic abc"}],
)
async def test_protected_route_needs_valid_token(client: AsyncClient, headers: dict) -> None:
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_expired_token_rejected(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client, "old@example.com")
    user = await db.scalar(select(User))
    assert user is not None
    old = create_access_token(
        user.id, expires_minutes=1, now=datetime.now(UTC) - timedelta(hours=1)
    )
    assert (await client.get("/auth/me", headers=bearer(old))).status_code == 401


async def test_admin_only_route(client: AsyncClient, db: AsyncSession) -> None:
    token = await signup(client, "boss@example.com")
    assert (await client.get("/_test/admin-only", headers=bearer(token))).status_code == 403
    await db.execute(text("UPDATE users SET role = 'admin'"))
    await db.commit()
    db.expire_all()
    assert (await client.get("/_test/admin-only", headers=bearer(token))).status_code == 200


async def test_users_only_see_their_own_rows(client: AsyncClient, db: AsyncSession) -> None:
    token_a = await signup(client, "a@example.com")
    token_b = await signup(client, "b@example.com")
    users = {u.email: u for u in (await db.scalars(select(User))).all()}
    db.add(BrokerAccount(user_id=users["a@example.com"].id, broker="dhan", label="A's Dhan"))
    db.add(BrokerAccount(user_id=users["b@example.com"].id, broker="dhan", label="B's Dhan"))
    await db.commit()

    a = (await client.get("/_test/my-brokers", headers=bearer(token_a))).json()
    b = (await client.get("/_test/my-brokers", headers=bearer(token_b))).json()
    assert a == ["A's Dhan"]
    assert b == ["B's Dhan"]


async def test_auth_events_recorded_without_password(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client, "audit@example.com")
    await client.post("/auth/login", json={"email": "audit@example.com", "password": "wrong-one"})
    events = (await db.scalars(select(EventLog).order_by(EventLog.id))).all()
    assert [e.message for e in events] == ["signup", "login failed"]
    assert all(PW not in str(e.payload) and "wrong-one" not in str(e.payload) for e in events)
