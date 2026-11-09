"""User strategies: library + assignment to a section (intraday / swing / options / crypto).

A strategy trades in at most one section. Only draft or paused strategies can be moved
between sections or deleted, so nothing that is running changes under its feet.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, owned_by
from app.core.events import record_event
from app.models import Strategy, StrategyVersion, User
from app.schemas.strategy import StrategyCreate, StrategyOut, StrategyStatusChange, StrategyUpdate
from app.strategies.catalog import catalog

router = APIRouter(prefix="/strategies", tags=["strategies"])

_MOVABLE = ("draft", "paused")


@router.get("/templates")
async def list_templates(_: CurrentUser) -> list[dict[str, Any]]:
    return catalog()


@router.get("", response_model=list[StrategyOut])
async def list_strategies(
    user: CurrentUser,
    db: DbSession,
    section: Literal["intraday", "swing", "options", "crypto", "none"] | None = Query(None),
) -> list[Strategy]:
    stmt = owned_by(Strategy, user).order_by(Strategy.created_at.desc())
    if section == "none":
        stmt = stmt.where(Strategy.section.is_(None))
    elif section is not None:
        stmt = stmt.where(Strategy.section == section)
    return list((await db.scalars(stmt)).all())


async def _get_owned(db: DbSession, user: User, strategy_id: uuid.UUID) -> Strategy:
    s = await db.scalar(owned_by(Strategy, user).where(Strategy.id == strategy_id))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    return s


def _snapshot(s: Strategy) -> StrategyVersion:
    return StrategyVersion(
        user_id=s.user_id,
        strategy_id=s.id,
        version=s.version,
        name=s.name,
        params=s.params,
        rules=s.rules,
    )


async def _commit_or_409(db: DbSession) -> None:
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a strategy with this name"
        ) from None


@router.post("", response_model=StrategyOut, status_code=status.HTTP_201_CREATED)
async def create_strategy(body: StrategyCreate, user: CurrentUser, db: DbSession) -> Strategy:
    s = Strategy(
        user_id=user.id,
        name=body.name,
        section=body.section,
        kind="template",
        template_key=body.template_key,
        params=body.params.model_dump(mode="json"),
        status="draft",
        version=1,
    )
    db.add(s)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a strategy with this name"
        ) from None
    db.add(_snapshot(s))
    await record_event(
        db,
        "system",
        "strategy created",
        user_id=user.id,
        strategy_id=str(s.id),
        template_key=s.template_key,
        section=s.section,
    )
    await _commit_or_409(db)
    await db.refresh(s)
    return s


@router.get("/{strategy_id}", response_model=StrategyOut)
async def get_strategy(strategy_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Strategy:
    return await _get_owned(db, user, strategy_id)


@router.patch("/{strategy_id}", response_model=StrategyOut)
async def update_strategy(
    strategy_id: uuid.UUID, body: StrategyUpdate, user: CurrentUser, db: DbSession
) -> Strategy:
    s = await _get_owned(db, user, strategy_id)
    sent = body.model_fields_set

    if "section" in sent and body.section != s.section:
        if s.status not in _MOVABLE:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Pause the strategy before moving it (it is {s.status})",
            )
        s.section = body.section

    content_changed = False
    if "name" in sent and body.name is not None and body.name != s.name:
        s.name = body.name
        content_changed = True
    if "params" in sent and body.params is not None:
        new_params = body.params.model_dump(mode="json")
        if new_params != s.params:
            s.params = new_params
            content_changed = True

    if content_changed:
        s.version += 1
        db.add(_snapshot(s))

    await record_event(
        db,
        "system",
        "strategy updated",
        user_id=user.id,
        strategy_id=str(s.id),
        section=s.section,
        version=s.version,
    )
    await _commit_or_409(db)
    await db.refresh(s)
    return s


@router.post("/{strategy_id}/status", response_model=StrategyOut)
async def change_status(
    strategy_id: uuid.UUID, body: StrategyStatusChange, user: CurrentUser, db: DbSession
) -> Strategy:
    """Start paper trading (the agents run it) or pause it. Live trading is Phase 4."""
    s = await _get_owned(db, user, strategy_id)
    if body.status == "paper":
        if s.section is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Add the strategy to a section first")
        if s.status not in ("draft", "paused", "paper"):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot paper-trade from {s.status}")
    s.status = body.status
    await record_event(
        db,
        "system",
        f"strategy {'started paper trading' if body.status == 'paper' else 'paused'}",
        user_id=user.id,
        strategy_id=str(s.id),
        section=s.section,
    )
    await db.commit()
    await db.refresh(s)
    return s


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy(strategy_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    s = await _get_owned(db, user, strategy_id)
    if s.status not in _MOVABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Pause the strategy first (it is {s.status})"
        )
    await db.delete(s)
    await record_event(db, "system", "strategy deleted", user_id=user.id, strategy_id=str(s.id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
