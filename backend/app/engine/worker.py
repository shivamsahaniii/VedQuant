"""Engine process: reacts to every new candle.

* every new NIFTY candle: recompute the market context ("market mood"),
* every closed candle: run the agent chain for users' running strategies (app/engine/pipeline.py),
* every live price of a symbol with an open paper trade: check its stop and target,
* every 20 s after 15:15 IST: square off open intraday paper trades.

Run: python -m app.engine.worker   (docker compose service `engine`)

Redis:
  vq:context   str      latest market context JSON
  vq:context   channel  same JSON, published on every update
  vq:signals   channel  every new signal (with user_id; the API forwards it only to that user)
  vq:trades    channel  trade opened / closed events (with user_id)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.feed import CANDLES_CHANNEL, QUOTES_KEY, TICKS_CHANNEL
from app.data.source import FEED_KEY, load_calendar, parse_status
from app.engine.context import MIN_BARS, MarketContext, compute_context
from app.engine.nse import SESSION, ist
from app.engine.pipeline import SIGNALS_CHANNEL, OddsPools, on_candle, signal_payload
from app.models import Candle, Trade
from app.orders.paper import on_price, square_off

CONTEXT_KEY = "vq:context"
CONTEXT_CHANNEL = "vq:context"
INDEX_EXCHANGE, INDEX_SYMBOL = "NSE", "NIFTY50"
LOOKBACK = timedelta(days=4)
MAX_BARS = 400


async def load_index_candles(session: AsyncSession, now: datetime) -> tuple[pd.DataFrame, str]:
    """NIFTY candles for the context: 5m once there are enough, else 1m (warming up)."""
    for tf in ("5m", "1m"):
        rows = (
            await session.scalars(
                select(Candle)
                .where(
                    Candle.exchange == INDEX_EXCHANGE,
                    Candle.symbol == INDEX_SYMBOL,
                    Candle.timeframe == tf,
                    Candle.ts >= now - LOOKBACK,
                )
                .order_by(Candle.ts.desc())
                .limit(MAX_BARS)
            )
        ).all()
        if len(rows) >= MIN_BARS or tf == "1m":
            df = pd.DataFrame(
                [
                    {
                        "ts": r.ts,
                        "open": float(r.open),
                        "high": float(r.high),
                        "low": float(r.low),
                        "close": float(r.close),
                        "volume": float(r.volume),
                    }
                    for r in reversed(rows)
                ],
                columns=["ts", "open", "high", "low", "close", "volume"],
            )
            if not df.empty:
                df["ts"] = pd.to_datetime(df["ts"], utc=True)
            return df, tf
    raise AssertionError("unreachable")  # pragma: no cover


def stocks_from_quotes(raw: dict[str, str]) -> dict[str, tuple[float, float]]:
    """symbol -> (day open, latest price), excluding the index."""
    out: dict[str, tuple[float, float]] = {}
    for value in raw.values():
        q = json.loads(value)
        if q.get("symbol") == INDEX_SYMBOL:
            continue
        out[q["symbol"]] = (float(q["open"]), float(q["ltp"]))
    return out


async def refresh_context(session: AsyncSession, redis: Any, now: datetime) -> MarketContext:
    df, tf = await load_index_candles(session, now)
    stocks = stocks_from_quotes(await redis.hgetall(QUOTES_KEY))
    ctx = compute_context(df, stocks, now, tf)
    payload = json.dumps(ctx.as_dict())
    await redis.set(CONTEXT_KEY, payload)
    await redis.publish(CONTEXT_CHANNEL, payload)
    return ctx


TRADES_CHANNEL = "vq:trades"
SQUARE_OFF_EVERY_S = 20


async def handle_candle(
    db: AsyncSession, redis: Any, bar: dict[str, Any], now: datetime, pools: OddsPools
) -> list[dict[str, Any]]:
    """Run the agent chain for one closed candle; returns the new signals (already committed)."""
    raw = await redis.hget(QUOTES_KEY, f"{bar['exchange']}:{bar['symbol']}")
    ltp = Decimal(json.loads(raw)["ltp"]) if raw else None
    feed = parse_status(await redis.get(FEED_KEY))
    owner = uuid.UUID(feed.owner_user_id) if feed and feed.is_real and feed.owner_user_id else None
    signals = await on_candle(
        db,
        bar,
        now=now,
        ltp=ltp,
        context_raw=await redis.get(CONTEXT_KEY),
        pools=pools,
        calendar=await load_calendar(db),
        only_user=owner,
    )
    await db.commit()
    payloads = [signal_payload(s) for s in signals]
    for p in payloads:
        await redis.publish(SIGNALS_CHANNEL, json.dumps(p))
        if p["status"] == "taken":
            await redis.publish(
                TRADES_CHANNEL, json.dumps({"user_id": p["user_id"], "event": "opened"})
            )
    return payloads


async def handle_tick(db: AsyncSession, redis: Any, quote: dict[str, Any], now: datetime) -> int:
    """Check one live price against open paper trades' stops and targets."""
    closed = await on_price(db, quote["exchange"], quote["symbol"], Decimal(str(quote["ltp"])), now)
    if closed:
        await db.commit()
        for t in closed:
            await redis.publish(
                TRADES_CHANNEL,
                json.dumps({"user_id": str(t.user_id), "event": "closed", "reason": t.exit_reason}),
            )
    return len(closed)


async def handle_square_off(db: AsyncSession, redis: Any, now: datetime) -> int:
    """After 15:15 IST (or before the open), close every open intraday paper trade at market."""
    t = ist(now).time()
    if SESSION.open <= t < SESSION.square_off:
        return 0
    prices = {}
    for value in (await redis.hgetall(QUOTES_KEY)).values():
        q = json.loads(value)
        prices[(q["exchange"], q["symbol"])] = Decimal(str(q["ltp"]))
    closed = await square_off(db, prices, now)
    if closed:
        await db.commit()
        for tr in closed:
            await redis.publish(
                TRADES_CHANNEL,
                json.dumps({"user_id": str(tr.user_id), "event": "closed", "reason": "square_off"}),
            )
    return len(closed)


async def run() -> None:  # pragma: no cover - long-running process
    import redis.asyncio as aioredis

    from app.core.config import get_settings
    from app.core.db import get_sessionmaker
    from app.core.logging import configure_logging, get_logger

    configure_logging("INFO")
    log = get_logger("app.engine")
    redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    sessionmaker = get_sessionmaker()
    pools = OddsPools()
    open_symbols: set[tuple[str, str]] = set()

    async def refresh_open() -> None:
        async with sessionmaker() as db:
            rows = await db.execute(
                select(Trade.exchange, Trade.symbol).where(Trade.status == "open").distinct()
            )
            open_symbols.clear()
            open_symbols.update((e, s) for e, s in rows.all())

    async def update_context(reason: str) -> None:
        async with sessionmaker() as session:
            ctx = await refresh_context(session, redis, datetime.now(UTC))
        log.info("market context", reason=reason, summary=ctx.summary, bias=ctx.bias)

    async def square_off_loop() -> None:
        while True:
            try:
                async with sessionmaker() as db:
                    n = await handle_square_off(db, redis, datetime.now(UTC))
                if n:
                    log.info("square-off", closed=n)
                    await refresh_open()
            except Exception:  # noqa: BLE001
                log.exception("square-off error")
            await asyncio.sleep(SQUARE_OFF_EVERY_S)

    asyncio.create_task(square_off_loop())  # noqa: RUF006 - lives as long as the process
    while True:
        try:
            await update_context("startup")
            await refresh_open()
            pubsub = redis.pubsub()
            await pubsub.subscribe(CANDLES_CHANNEL, TICKS_CHANNEL)
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = json.loads(msg["data"])
                now = datetime.now(UTC)
                if msg["channel"] == TICKS_CHANNEL:
                    if (data["exchange"], data["symbol"]) in open_symbols:
                        async with sessionmaker() as db:
                            if await handle_tick(db, redis, data, now):
                                await refresh_open()
                    continue
                if data.get("symbol") == INDEX_SYMBOL:
                    await update_context(f"new {data.get('timeframe')} candle")
                async with sessionmaker() as db:
                    signals = await handle_candle(db, redis, data, now, pools)
                for p in signals:
                    log.info(
                        "signal",
                        symbol=p["symbol"],
                        side=p["side"],
                        rule=p["rule"],
                        status=p["status"],
                        why=p["status_reason"],
                    )
                if any(p["status"] == "taken" for p in signals):
                    await refresh_open()
        except Exception:  # noqa: BLE001 - keep the engine alive
            log.exception("engine error, restarting in 5s")
            await asyncio.sleep(5)


def main() -> None:  # pragma: no cover
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
