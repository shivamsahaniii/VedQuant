"""Signals, paper positions, the trade journal, and the user's own kill switch.

Every query is filtered to the current user (owned_by); another user's trade is a 404.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select, update

from app.api.deps import CurrentUser, DbSession, owned_by
from app.core.events import record_event
from app.core.redis import get_redis
from app.data.feed import QUOTES_KEY
from app.engine.nse import ist
from app.models import Signal, Strategy, Trade
from app.orders.paper import close_trade, market_fill, square_off

router = APIRouter(tags=["trading"])


def _s(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


async def _prices() -> dict[tuple[str, str], Decimal]:
    out = {}
    for value in (await get_redis().hgetall(QUOTES_KEY)).values():
        q = json.loads(value)
        out[(q["exchange"], q["symbol"])] = Decimal(str(q["ltp"]))
    return out


def _trade_out(t: Trade, names: dict[uuid.UUID, str], ltp: Decimal | None) -> dict[str, Any]:
    sign = 1 if t.side == "buy" else -1
    unreal = (ltp - t.entry_price) * t.qty * sign if (t.status == "open" and ltp) else None
    return {
        "id": str(t.id),
        "strategy_id": _s(t.strategy_id) if t.strategy_id else None,
        "strategy": names.get(t.strategy_id, "") if t.strategy_id else "",
        "section": t.section,
        "symbol": t.symbol,
        "side": t.side,
        "qty": t.qty,
        "entry_price": _s(t.entry_price),
        "entry_at": t.entry_at.isoformat(),
        "stop": _s(t.stop),
        "target": _s(t.target),
        "max_loss": _s(t.max_loss),
        "status": t.status,
        "ltp": _s(ltp),
        "unrealised": _s(unreal),
        "exit_price": _s(t.exit_price),
        "exit_at": t.exit_at.isoformat() if t.exit_at else None,
        "exit_reason": t.exit_reason,
        "gross_pnl": _s(t.gross_pnl),
        "charges": _s(t.charges),
        "net_pnl": _s(t.net_pnl),
    }


async def _names(db, user) -> dict[uuid.UUID, str]:
    rows = await db.execute(select(Strategy.id, Strategy.name).where(Strategy.user_id == user.id))
    return dict(rows.all())


@router.get("/signals")
async def list_signals(
    user: CurrentUser,
    db: DbSession,
    section: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    q = owned_by(Signal, user).order_by(Signal.created_at.desc()).limit(limit)
    if section:
        q = q.where(Signal.section == section)
    names = await _names(db, user)
    return [
        {
            "id": str(s.id),
            "strategy_id": str(s.strategy_id),
            "strategy": names.get(s.strategy_id, ""),
            "section": s.section,
            "symbol": s.symbol,
            "side": s.side,
            "rule": s.rule,
            "price": str(s.price),
            "reason": s.reason,
            "status": s.status,
            "status_reason": s.status_reason,
            "plan": s.plan,
            "odds": s.odds,
            "risk": s.risk,
            "mood": s.mood,
            "bar_ts": s.bar_ts.isoformat(),
            "created_at": s.created_at.isoformat(),
        }
        for s in (await db.scalars(q)).all()
    ]


@router.get("/trades")
async def list_trades(
    user: CurrentUser,
    db: DbSession,
    status_: Literal["open", "closed"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    q = owned_by(Trade, user).order_by(Trade.entry_at.desc()).limit(limit)
    if status_:
        q = q.where(Trade.status == status_)
    prices = await _prices()
    names = await _names(db, user)
    return [
        _trade_out(t, names, prices.get((t.exchange, t.symbol)))
        for t in (await db.scalars(q)).all()
    ]


@router.get("/trading/summary")
async def summary(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    trades = (await db.scalars(owned_by(Trade, user))).all()
    prices = await _prices()
    names = await _names(db, user)
    today = ist(datetime.now(UTC)).date()
    closed = [t for t in trades if t.status == "closed"]
    open_ = [t for t in trades if t.status == "open"]
    unreal = Decimal(0)
    for t in open_:
        ltp = prices.get((t.exchange, t.symbol))
        if ltp:
            unreal += (ltp - t.entry_price) * t.qty * (1 if t.side == "buy" else -1)
    today_closed = [t for t in closed if t.exit_at and ist(t.exit_at).date() == today]
    per: dict[str, dict[str, Any]] = {}
    for t in closed:
        k = names.get(t.strategy_id, "Manual") if t.strategy_id else "Manual"
        row = per.setdefault(k, {"strategy": k, "trades": 0, "wins": 0, "net": Decimal(0)})
        row["trades"] += 1
        row["wins"] += 1 if (t.net_pnl or 0) > 0 else 0
        row["net"] += t.net_pnl or Decimal(0)
    wins = sum(1 for t in closed if (t.net_pnl or 0) > 0)
    return {
        "realised_today": str(sum((t.net_pnl or Decimal(0) for t in today_closed), Decimal(0))),
        "unrealised": str(unreal),
        "charges_today": str(sum((t.charges or Decimal(0) for t in today_closed), Decimal(0))),
        "open_positions": len(open_),
        "trades_today": sum(1 for t in trades if ist(t.entry_at).date() == today),
        "closed_trades": len(closed),
        "win_rate": round(wins / len(closed) * 100, 1) if closed else None,
        "realised_total": str(sum((t.net_pnl or Decimal(0) for t in closed), Decimal(0))),
        "per_strategy": [
            {**r, "net": str(r["net"]), "win_rate": round(r["wins"] / r["trades"] * 100, 1)}
            for r in per.values()
        ],
    }


@router.post("/trades/{trade_id}/close")
async def close_one(trade_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Close an open paper position at market. Getting out is never blocked."""
    t = await db.scalar(owned_by(Trade, user).where(Trade.id == trade_id))
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade not found")
    if t.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Trade is already closed")
    ltp = (await _prices()).get((t.exchange, t.symbol))
    if ltp is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No live price to close at; try again")
    fill = market_fill("sell" if t.side == "buy" else "buy", ltp, t.tick)
    await close_trade(db, t, fill, datetime.now(UTC), "manual")
    await record_event(
        db,
        "order",
        f"manual close {t.symbol}",
        user_id=user.id,
        trade_id=str(t.id),
        price=str(fill),
    )
    await db.commit()
    return _trade_out(t, await _names(db, user), ltp)


@router.post("/trading/kill-switch")
async def kill_switch(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Close every open paper position at market and pause every running strategy."""
    closed = await square_off(
        db,
        await _prices(),
        datetime.now(UTC),
        user_id=user.id,
        reason="kill_switch",
        intraday_only=False,
    )
    paused = await db.execute(
        update(Strategy)
        .where(Strategy.user_id == user.id, Strategy.status == "paper")
        .values(status="paused")
    )
    await record_event(
        db,
        "risk",
        "kill switch",
        user_id=user.id,
        level="warning",
        closed=len(closed),
        paused=paused.rowcount,
    )
    await db.commit()
    return {"closed": len(closed), "paused": paused.rowcount}
