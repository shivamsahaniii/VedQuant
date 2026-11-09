from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import login_limiter
from app.core.db import get_session
from app.main import app
from app.models import StrategyVersion

PW = "a-strong-password-1"


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


def body(**kw) -> dict:
    base = {
        "name": "My ORB",
        "template_key": "orb",
        "section": "intraday",
        "params": {"timeframe": "5m", "symbols": "reliance, sbin ,SBIN", "stop_loss_pct": "1.5"},
    }
    base.update(kw)
    return base


async def test_templates_catalog(client: AsyncClient) -> None:
    h = await user(client, "t@example.com")
    r = await client.get("/strategies/templates", headers=h)
    keys = [t["key"] for t in r.json()]
    assert keys[:3] == ["orb", "vwap_cross", "supertrend"]


async def test_create_and_list_by_section(client: AsyncClient, db: AsyncSession) -> None:
    h = await user(client, "a@example.com")
    r = await client.post("/strategies", json=body(), headers=h)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["status"] == "draft" and s["version"] == 1 and s["section"] == "intraday"
    assert s["params"]["symbols"] == ["RELIANCE", "SBIN"]  # cleaned + de-duplicated
    assert s["params"]["stop_loss_pct"] == "1.5"

    await client.post("/strategies", json=body(name="Lib only", section=None), headers=h)
    await client.post(
        "/strategies",
        json=body(
            name="Swingy", template_key="ema_cross", section="swing", params={"timeframe": "1d"}
        ),
        headers=h,
    )

    names = lambda r: sorted(x["name"] for x in r.json())  # noqa: E731
    assert names(await client.get("/strategies?section=intraday", headers=h)) == ["My ORB"]
    assert names(await client.get("/strategies?section=swing", headers=h)) == ["Swingy"]
    assert names(await client.get("/strategies?section=none", headers=h)) == ["Lib only"]
    assert len((await client.get("/strategies", headers=h)).json()) == 3
    assert await db.scalar(select(func.count()).select_from(StrategyVersion)) == 3


@pytest.mark.parametrize(
    "bad",
    [
        {"template_key": "nope"},
        {"name": "   "},
        {"section": "weekly"},
        {"params": {"timeframe": "7m"}},
        {"params": {"stop_loss_pct": "0"}},
        {"params": {"symbols": ["BAD SYMBOL!"]}},
        {"params": {"unknown": 1}},
    ],
)
async def test_validation(client: AsyncClient, bad: dict) -> None:
    h = await user(client, "v@example.com")
    r = await client.post("/strategies", json=body(**bad), headers=h)
    assert r.status_code == 422


async def test_duplicate_name_conflict(client: AsyncClient) -> None:
    h = await user(client, "d@example.com")
    assert (await client.post("/strategies", json=body(), headers=h)).status_code == 201
    r = await client.post("/strategies", json=body(section="swing"), headers=h)
    assert r.status_code == 409


async def test_add_to_section_move_and_remove(client: AsyncClient) -> None:
    h = await user(client, "m@example.com")
    sid = (await client.post("/strategies", json=body(section=None), headers=h)).json()["id"]

    r = await client.patch(f"/strategies/{sid}", json={"section": "swing"}, headers=h)
    assert r.json()["section"] == "swing"
    assert r.json()["version"] == 1  # moving is not a content change

    r = await client.patch(f"/strategies/{sid}", json={"section": None}, headers=h)
    assert r.json()["section"] is None


async def test_edit_bumps_version_and_snapshots(client: AsyncClient, db: AsyncSession) -> None:
    h = await user(client, "e@example.com")
    sid = (await client.post("/strategies", json=body(), headers=h)).json()["id"]
    r = await client.patch(
        f"/strategies/{sid}", json={"params": {"timeframe": "15m", "stop_loss_pct": 2}}, headers=h
    )
    assert r.json()["version"] == 2
    assert r.json()["params"]["timeframe"] == "15m"
    versions = (await db.scalars(select(StrategyVersion.version).order_by("version"))).all()
    assert versions == [1, 2]


async def test_running_strategy_cannot_move_or_delete(
    client: AsyncClient, db: AsyncSession
) -> None:
    h = await user(client, "r@example.com")
    sid = (await client.post("/strategies", json=body(), headers=h)).json()["id"]
    await db.execute(text("UPDATE strategies SET status = 'paper'"))
    await db.commit()
    db.expire_all()
    r = await client.patch(f"/strategies/{sid}", json={"section": "swing"}, headers=h)
    assert r.status_code == 409
    assert (await client.delete(f"/strategies/{sid}", headers=h)).status_code == 409


async def test_delete_draft(client: AsyncClient) -> None:
    h = await user(client, "x@example.com")
    sid = (await client.post("/strategies", json=body(), headers=h)).json()["id"]
    assert (await client.delete(f"/strategies/{sid}", headers=h)).status_code == 204
    assert (await client.get(f"/strategies/{sid}", headers=h)).status_code == 404


async def test_users_cannot_touch_each_others_strategies(client: AsyncClient) -> None:
    a = await user(client, "alice@example.com")
    b = await user(client, "bob@example.com")
    sid = (await client.post("/strategies", json=body(), headers=a)).json()["id"]

    assert (await client.get("/strategies", headers=b)).json() == []
    assert (await client.get(f"/strategies/{sid}", headers=b)).status_code == 404
    patch = await client.patch(f"/strategies/{sid}", json={"section": "swing"}, headers=b)
    assert patch.status_code == 404
    assert (await client.delete(f"/strategies/{sid}", headers=b)).status_code == 404
    # Bob can use the same name: names are unique per user only.
    assert (await client.post("/strategies", json=body(), headers=b)).status_code == 201


async def test_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/strategies")).status_code == 401
