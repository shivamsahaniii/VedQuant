"""Markets: each user's indices, stocks and crypto lists, with live data status per instrument."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.connections import get_prefs, get_setting, set_setting
from app.api.deps import CurrentUser, DbSession, owned_by
from app.connectors.catalog import BY_KEY as CONNECTORS
from app.connectors.catalog import AssetClass
from app.core.redis import get_redis
from app.data.feed import QUOTES_KEY
from app.data.source import FEED_KEY, FeedStatus, can_see_feed, parse_status
from app.markets.catalog import (
    BY_KEY,
    CATALOG,
    DEFAULTS,
    EXCHANGES,
    SIMULATED,
    tv_symbol,
    valid_symbol,
)
from app.models import Candle, User, WatchItem

IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/markets", tags=["markets"])
SEEDED_KEY = "watchlist_seeded"
MAX_ITEMS = 200


async def _seed(db: AsyncSession, user: User) -> None:
    if await get_setting(db, user, SEEDED_KEY):
        return
    for i, key in enumerate(DEFAULTS):
        m = BY_KEY[key]
        db.add(
            WatchItem(
                user_id=user.id,
                asset_class=m.asset_class,
                exchange=m.exchange,
                symbol=m.symbol,
                name=m.name,
                position=i,
            )
        )
    await set_setting(db, user, SEEDED_KEY, True)
    await db.commit()


def _data_status(
    asset: str,
    exchange: str,
    symbol: str,
    source: str | None,
    has_quote: bool,
    feed: FeedStatus | None = None,
) -> dict[str, Any]:
    if source is None:
        return {
            "state": "no_source",
            "label": "No data source",
            "hint": f"Choose a {asset} data source in Settings → Connections",
        }
    c = CONNECTORS[source]
    if source == "paper":
        if feed is not None and feed.is_real:
            return {
                "state": "pending",
                "label": "Simulator off",
                "hint": "A real data feed is running; choose it for this market.",
            }
        if (exchange, symbol) in SIMULATED:
            return {
                "state": "live" if has_quote else "waiting",
                "label": "Simulated",
                "source": c.name,
            }
        return {
            "state": "unsupported",
            "label": "Not in simulator",
            "hint": "The simulator covers NIFTY 50 and 10 stocks. Connect a broker for this one.",
        }
    # A real broker: prices flow only while that broker's feed is the one running for this user.
    if feed is None or feed.source != source:
        return {
            "state": "pending",
            "label": c.name,
            "source": c.name,
            "hint": f"Waiting for the {c.name} feed to start",
        }
    if has_quote:
        label = c.name if feed.state == "live" else f"{c.name} · last price"
        return {"state": "live", "label": label, "source": c.name, "hint": feed.message}
    if f"{exchange}:{symbol}" in feed.missing:
        return {
            "state": "unsupported",
            "label": "Not found",
            "source": c.name,
            "hint": f"{c.name} has no instrument {exchange}:{symbol}",
        }
    return {
        "state": "waiting" if feed.state == "live" else "pending",
        "label": c.name,
        "source": c.name,
        "hint": feed.message,
    }


async def _last_close(db: Any, exchange: str, symbol: str) -> dict[str, Any] | None:
    """Last real 5m close, and its change vs the previous trading day's close."""
    last = await db.scalar(
        select(Candle)
        .where(Candle.exchange == exchange, Candle.symbol == symbol, Candle.timeframe == "5m")
        .order_by(Candle.ts.desc())
        .limit(1)
    )
    if last is None:
        return None
    day = last.ts.astimezone(IST).date()
    day_start = datetime(day.year, day.month, day.day, tzinfo=IST)
    prev = await db.scalar(
        select(Candle.close)
        .where(
            Candle.exchange == exchange,
            Candle.symbol == symbol,
            Candle.timeframe == "5m",
            Candle.ts < day_start,
        )
        .order_by(Candle.ts.desc())
        .limit(1)
    )
    change = last.close - prev if prev else Decimal(0)
    pct = (change / prev * 100) if prev else Decimal(0)
    return {
        "exchange": exchange,
        "symbol": symbol,
        "ltp": str(last.close),
        "change": str(change.quantize(Decimal("0.01"))),
        "change_pct": str(pct.quantize(Decimal("0.01"))),
        "prev_close": str(prev) if prev else None,
        "last_close": True,
        "as_of": (last.ts + timedelta(minutes=5)).isoformat(),
    }


@router.get("/catalog")
async def market_catalog(
    user: CurrentUser, db: DbSession, asset: AssetClass | None = None
) -> dict[str, Any]:
    followed = set(
        (
            await db.execute(
                select(WatchItem.exchange, WatchItem.symbol).where(WatchItem.user_id == user.id)
            )
        )
        .tuples()
        .all()
    )
    items = [
        {**m.as_dict(), "followed": (m.exchange, m.symbol) in followed}
        for m in CATALOG
        if asset is None or m.asset_class == asset
    ]
    return {"items": items, "exchanges": EXCHANGES}


@router.get("/watchlist")
async def watchlist(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    await _seed(db, user)
    prefs = await get_prefs(db, user)
    rows = (
        await db.scalars(
            owned_by(WatchItem, user).order_by(WatchItem.position, WatchItem.created_at)
        )
    ).all()
    redis = get_redis()
    feed = parse_status(await redis.get(FEED_KEY))
    quotes = await redis.hgetall(QUOTES_KEY) if can_see_feed(feed, user.id) else {}
    out = []
    for w in rows:
        raw = quotes.get(f"{w.exchange}:{w.symbol}")
        source = prefs["data_sources"].get(w.asset_class)
        matches = (source == "paper" and (feed is None or not feed.is_real)) or (
            feed is not None and feed.is_real and feed.source == source
        )
        q = json.loads(raw) if (raw and matches) else None
        if q is None and matches and feed is not None and feed.is_real and feed.state != "live":
            q = await _last_close(db, w.exchange, w.symbol)  # market closed: last real close
        out.append(
            {
                "id": str(w.id),
                "asset_class": w.asset_class,
                "exchange": w.exchange,
                "symbol": w.symbol,
                "name": w.name,
                "tv": tv_symbol(w.asset_class, w.exchange, w.symbol),
                "quote": q,
                "data": _data_status(
                    w.asset_class, w.exchange, w.symbol, source, q is not None, feed
                ),
            }
        )
    return {"items": out, "preferences": prefs}


class WatchIn(BaseModel):
    asset_class: AssetClass
    exchange: str = Field(min_length=2, max_length=16)
    symbol: str = Field(min_length=1, max_length=30)
    name: str = Field(default="", max_length=80)

    @field_validator("exchange", "symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


@router.post("/watchlist", status_code=status.HTTP_201_CREATED)
async def add_item(body: WatchIn, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    if body.exchange not in EXCHANGES[body.asset_class]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{body.asset_class} trade on {', '.join(EXCHANGES[body.asset_class])}",
        )
    if not valid_symbol(body.symbol):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid symbol")
    await _seed(db, user)
    count = await db.scalar(
        select(func.count()).select_from(WatchItem).where(WatchItem.user_id == user.id)
    )
    if count >= MAX_ITEMS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"At most {MAX_ITEMS} instruments")
    if await db.scalar(
        owned_by(WatchItem, user).where(
            WatchItem.exchange == body.exchange, WatchItem.symbol == body.symbol
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{body.symbol} is already in your list")
    known = BY_KEY.get((body.exchange, body.symbol))
    w = WatchItem(
        user_id=user.id,
        asset_class=known.asset_class if known else body.asset_class,
        exchange=body.exchange,
        symbol=body.symbol,
        name=(known.name if known else body.name.strip()) or body.symbol,
        position=count,
    )
    db.add(w)
    await db.commit()
    return {"id": str(w.id), "symbol": w.symbol}


@router.delete("/watchlist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    w = await db.scalar(owned_by(WatchItem, user).where(WatchItem.id == item_id))
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not in your list")
    await db.delete(w)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
