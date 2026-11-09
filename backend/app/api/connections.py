"""Connections: the provider catalog, each user's choices (data source per market, chart provider),
and requests for connectors that are not built yet."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, owned_by
from app.connectors.catalog import ASSET_CLASSES, BY_KEY, CONNECTORS, AssetClass
from app.core.events import record_event
from app.models import BrokerAccount, User, UserSetting

router = APIRouter(prefix="/connectors", tags=["connections"])

PREFS_KEY = "connections"
REQUESTS_KEY = "connector_requests"
DEFAULT_PREFS: dict[str, Any] = {
    "chart_provider": "vedquant_charts",
    "data_sources": {"indices": "paper", "stocks": "paper", "crypto": None},
}


async def get_setting(db: AsyncSession, user: User, key: str) -> Any:
    row = await db.get(UserSetting, (user.id, key))
    return row.value if row else None


async def set_setting(db: AsyncSession, user: User, key: str, value: Any) -> None:
    row = await db.get(UserSetting, (user.id, key))
    if row is None:
        db.add(UserSetting(user_id=user.id, key=key, value=value))
    else:
        row.value = value


async def get_prefs(db: AsyncSession, user: User) -> dict[str, Any]:
    saved = await get_setting(db, user, PREFS_KEY) or {}
    return {
        "chart_provider": saved.get("chart_provider", DEFAULT_PREFS["chart_provider"]),
        "data_sources": {**DEFAULT_PREFS["data_sources"], **saved.get("data_sources", {})},
    }


async def _connected_brokers(db: AsyncSession, user: User) -> dict[str, int]:
    rows = (await db.scalars(owned_by(BrokerAccount, user))).all()
    out: dict[str, int] = {}
    for a in rows:
        if a.status == "connected":
            out[a.broker] = out.get(a.broker, 0) + 1
    return out


@router.get("")
async def list_connectors(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    connected = await _connected_brokers(db, user)
    requested = set(await get_setting(db, user, REQUESTS_KEY) or [])
    prefs = await get_prefs(db, user)
    items = []
    for c in CONNECTORS:
        d = c.as_dict()
        d["connected_accounts"] = 1 if c.key == "paper" else connected.get(c.broker_key or "", 0)
        d["requested"] = c.key in requested
        d["in_use_for"] = [a for a, k in prefs["data_sources"].items() if k == c.key]
        if prefs["chart_provider"] == c.key:
            d["in_use_for"].append("charts")
        items.append(d)
    return {"connectors": items, "preferences": prefs}


class Preferences(BaseModel):
    chart_provider: str | None = None
    data_sources: dict[AssetClass, str | None] | None = None


@router.put("/preferences")
async def save_preferences(body: Preferences, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    prefs = await get_prefs(db, user)
    if body.chart_provider is not None:
        c = BY_KEY.get(body.chart_provider)
        if c is None or c.category != "charts":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown chart provider")
        if c.status != "available":
            raise HTTPException(status.HTTP_409_CONFLICT, f"{c.name} is not available yet")
        prefs["chart_provider"] = c.key
    if body.data_sources is not None:
        connected = await _connected_brokers(db, user)
        for asset, key in body.data_sources.items():
            if asset not in ASSET_CLASSES:
                continue
            if key is None:
                prefs["data_sources"][asset] = None
                continue
            c = BY_KEY.get(key)
            if c is None or asset not in c.assets or "market data" not in c.provides:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, f"{key} cannot provide {asset} data"
                )
            if c.status != "available":
                raise HTTPException(status.HTTP_409_CONFLICT, f"{c.name} is not available yet")
            if c.key != "paper" and not connected.get(c.broker_key or ""):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, f"Connect and test your {c.name} account first"
                )
            prefs["data_sources"][asset] = c.key
    await set_setting(db, user, PREFS_KEY, prefs)
    await record_event(db, "system", "connections updated", user_id=user.id, **prefs)
    await db.commit()
    return prefs


@router.post("/{key}/request")
async def request_connector(key: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    c = BY_KEY.get(key)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown connector")
    if c.status == "available":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{c.name} is already available")
    requested = list(await get_setting(db, user, REQUESTS_KEY) or [])
    if key not in requested:
        requested.append(key)
        await set_setting(db, user, REQUESTS_KEY, requested)
        await record_event(db, "system", f"connector requested: {key}", user_id=user.id)
        await db.commit()
    return {"requested": True}


async def request_counts(db: AsyncSession) -> dict[str, int]:
    """For admins: how many users asked for each connector (what to build next)."""
    rows = (await db.scalars(select(UserSetting).where(UserSetting.key == REQUESTS_KEY))).all()
    counts: dict[str, int] = {}
    for r in rows:
        for k in r.value or []:
            counts[k] = counts.get(k, 0) + 1
    return counts
