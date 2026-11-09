"""Market data for the dashboard: quote snapshot, recent candles, live quotes WebSocket.

WebSocket protocol (/ws/quotes):
  client -> {"type": "auth", "token": "<access token>"}   (first message, within 5 s)
  server -> {"type": "snapshot", "quotes": [...]}         (all current quotes)
  server -> {"type": "quote", "quote": {...}}             (every tick after that)
  server -> {"type": "context", "context": {...}}         (market mood, every new candle)
The token is sent as a message, never in the URL, so it can't end up in access logs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import InvalidTokenError, decode_access_token
from app.data.candles import bar_start
from app.data.feed import QUOTES_KEY, TICKS_CHANNEL
from app.data.source import (
    FEED_CHANNEL,
    FEED_KEY,
    FeedStatus,
    can_see_feed,
    parse_status,
    status_payload,
)
from app.engine.worker import CONTEXT_CHANNEL, CONTEXT_KEY, SIGNALS_CHANNEL, TRADES_CHANNEL
from app.models import Candle, User

router = APIRouter(tags=["market"])
log = get_logger("app.api.market")

INDEX_SYMBOLS = {"NIFTY50"}
AUTH_TIMEOUT_S = 5.0


def _sorted_quotes(raw: dict[str, str]) -> list[dict[str, Any]]:
    quotes = [json.loads(v) for v in raw.values()]
    return sorted(quotes, key=lambda q: (q["symbol"] not in INDEX_SYMBOLS, q["symbol"]))


async def _feed() -> FeedStatus | None:
    return parse_status(await get_redis().get(FEED_KEY))


@router.get("/market/feed")
async def feed_status(user: CurrentUser) -> dict[str, Any] | None:
    """Where prices come from right now (simulator or a user's real broker feed)."""
    st = await _feed()
    if st is None:
        return None
    if not can_see_feed(st, user.id):
        return {
            "source": "other",
            "state": "unavailable",
            "message": "Live prices need your own data source (Settings → Connections).",
        }
    return status_payload(st)


@router.get("/market/quotes")
async def quotes(user: CurrentUser) -> list[dict[str, Any]]:
    if not can_see_feed(await _feed(), user.id):
        return []
    return _sorted_quotes(await get_redis().hgetall(QUOTES_KEY))


@router.get("/market/context")
async def market_context(user: CurrentUser) -> dict[str, Any] | None:
    """Latest market mood (None until the engine has run once)."""
    if not can_see_feed(await _feed(), user.id):
        return None
    raw = await get_redis().get(CONTEXT_KEY)
    return json.loads(raw) if raw else None


class CandleOut(BaseModel):
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@router.get("/market/candles", response_model=list[CandleOut])
async def candles(
    user: CurrentUser,
    db: DbSession,
    symbol: str = Query(min_length=1, max_length=64),
    exchange: str = Query("NSE", max_length=16),
    timeframe: Literal["1m", "5m", "15m", "1h", "1d"] = "1m",
    limit: int = Query(60, ge=1, le=500),
) -> list[Any]:
    if not can_see_feed(await _feed(), user.id):
        return []
    # 15m and 1h are built from stored 5m candles (IST-aligned; 1h from 09:15).
    stored = "5m" if timeframe in ("15m", "1h") else timeframe
    per = {"15m": 3, "1h": 12}.get(timeframe, 1)
    rows = (
        await db.scalars(
            select(Candle)
            .where(
                Candle.exchange == exchange,
                Candle.symbol == symbol.upper(),
                Candle.timeframe == stored,
            )
            .order_by(Candle.ts.desc())
            .limit(limit * per)
        )
    ).all()
    rows = list(reversed(rows))
    if per == 1:
        return rows
    return aggregate(rows, timeframe)[-limit:]


def aggregate(rows: list[Candle], timeframe: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        start = bar_start(r.ts, timeframe)
        if out and out[-1]["ts"] == start:
            b = out[-1]
            b["high"], b["low"] = max(b["high"], r.high), min(b["low"], r.low)
            b["close"], b["volume"] = r.close, b["volume"] + r.volume
        else:
            out.append(
                {
                    "ts": start,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
            )
    return out


async def _authenticate(ws: WebSocket) -> User | None:
    try:
        msg = await asyncio.wait_for(ws.receive_json(), AUTH_TIMEOUT_S)
        if not isinstance(msg, dict) or msg.get("type") != "auth":
            return None
        user_id = decode_access_token(str(msg.get("token", "")))
    except (TimeoutError, InvalidTokenError, ValueError, WebSocketDisconnect):
        return None
    async with get_sessionmaker()() as db:
        user = await db.get(User, user_id)
    return user if user is not None and user.is_active else None


@router.websocket("/ws/quotes")
async def quotes_ws(ws: WebSocket) -> None:
    await ws.accept()
    user = await _authenticate(ws)
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Not authenticated")
        return

    redis = get_redis()
    pubsub = redis.pubsub()
    channels = (TICKS_CHANNEL, CONTEXT_CHANNEL, SIGNALS_CHANNEL, TRADES_CHANNEL, FEED_CHANNEL)
    private = {SIGNALS_CHANNEL: "signal", TRADES_CHANNEL: "trade"}
    me = str(user.id)
    await pubsub.subscribe(*channels)
    closed = asyncio.Event()

    async def watch_client() -> None:
        # Ends when the browser disconnects; incoming messages are ignored.
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            while True:
                await ws.receive_text()
        closed.set()

    watcher = asyncio.create_task(watch_client())
    try:
        ctx_raw = await redis.get(CONTEXT_KEY)
        feed = parse_status(await redis.get(FEED_KEY))
        visible = can_see_feed(feed, user.id)
        await ws.send_json(
            {
                "type": "snapshot",
                "quotes": _sorted_quotes(await redis.hgetall(QUOTES_KEY)) if visible else [],
                "context": json.loads(ctx_raw) if (ctx_raw and visible) else None,
                "feed": status_payload(feed) if (feed and visible) else None,
            }
        )
        while not closed.is_set():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not msg or msg.get("type") != "message":
                continue
            channel = msg.get("channel")
            if channel in private:
                # Signals and trades are per user: forward only this user's own events.
                data = json.loads(msg["data"])
                if data.get("user_id") == me:
                    await ws.send_json({"type": private[channel], private[channel]: data})
                continue
            if channel == FEED_CHANNEL:
                feed = parse_status(msg["data"])
                visible = can_see_feed(feed, user.id)
                if visible and feed is not None:
                    await ws.send_json({"type": "feed", "feed": status_payload(feed)})
                continue
            if not visible:
                continue  # another user's real feed: not shared
            kind = "context" if channel == CONTEXT_CHANNEL else "quote"
            await ws.send_text(f'{{"type":"{kind}","{kind}":' + msg["data"] + "}")
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        watcher.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(*channels)
            await pubsub.aclose()
