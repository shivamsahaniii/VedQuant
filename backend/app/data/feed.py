"""Market data feed process: ticks -> live quotes (Redis) + candles (DB) + events.

Run: python -m app.data.feed   (docker compose service `feed`)

Source today: the market simulator (paper broker demo feed). Later: a user's Dhan data
key through the Dhan adapter (same Tick type, nothing else changes).

Redis layout:
  vq:quotes              hash  "NSE:SBIN" -> quote JSON (ltp, day open/high/low, change, volume)
  vq:candle:NSE:SBIN:5m  str   last closed 5m bar JSON
  vq:ticks               pub/sub channel, one quote JSON per tick
  vq:candles             pub/sub channel, one bar JSON per closed bar ("new candle" event)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.brokers.base import Tick
from app.data.candles import IST, Bar, CandleBuilder
from app.models import Candle

QUOTES_KEY = "vq:quotes"
TICKS_CHANNEL = "vq:ticks"
CANDLES_CHANNEL = "vq:candles"
TIMEFRAMES = ("1m", "5m")


def candle_key(exchange: str, symbol: str, timeframe: str) -> str:
    return f"vq:candle:{exchange}:{symbol}:{timeframe}"


# ---------------------------------------------------------------- quotes


@dataclass
class _Day:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal


class QuoteBook:
    """Day open/high/low per symbol (resets when the IST date changes)."""

    def __init__(self) -> None:
        self._days: dict[tuple[str, str], _Day] = {}

    def update(self, tick: Tick) -> dict[str, Any]:
        key = (tick.exchange, tick.symbol)
        today = tick.ts.astimezone(IST).date()
        d = self._days.get(key)
        if d is None or d.day != today:
            d = _Day(today, tick.ltp, tick.ltp, tick.ltp)
            self._days[key] = d
        # Real feeds send the exchange's own day open/high/low; trust them over our own tracking
        # (the feed may start mid-day). The simulator sends none, so we track them ourselves.
        if tick.day_open:
            d.open = tick.day_open
        d.high = max(d.high, tick.ltp, tick.day_high or tick.ltp)
        d.low = min(d.low, tick.ltp, tick.day_low or tick.ltp)
        base = tick.prev_close or d.open  # change is measured from yesterday's close when known
        change = tick.ltp - base
        pct = (change / base * 100).quantize(Decimal("0.01")) if base else Decimal(0)
        return {
            "exchange": tick.exchange,
            "symbol": tick.symbol,
            "ltp": str(tick.ltp),
            "open": str(d.open),
            "high": str(d.high),
            "low": str(d.low),
            "change": str(change),
            "change_pct": str(pct),
            "prev_close": str(tick.prev_close) if tick.prev_close else None,
            "volume": tick.volume,
            "ts": tick.ts.astimezone(UTC).isoformat(),
        }


# ---------------------------------------------------------------- processing


class FeedSink(Protocol):
    async def quote(self, quote: dict[str, Any]) -> None: ...

    async def candles(self, bars: list[Bar]) -> None: ...


class FeedProcessor:
    def __init__(self, sink: FeedSink, timeframes: tuple[str, ...] = TIMEFRAMES) -> None:
        self.sink = sink
        self.builder = CandleBuilder(timeframes)
        self.quotes = QuoteBook()

    async def handle(self, tick: Tick) -> None:
        await self.sink.quote(self.quotes.update(tick))
        closed = self.builder.on_tick(tick)
        if closed:
            await self.sink.candles(closed)

    async def flush(self, now: datetime) -> None:
        closed = self.builder.flush(now)
        if closed:
            await self.sink.candles(closed)


async def upsert_bars(session: AsyncSession, bars: Iterable[Bar]) -> int:
    rows = [
        {
            "exchange": b.exchange,
            "symbol": b.symbol,
            "timeframe": b.timeframe,
            "ts": b.ts,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    if not rows:
        return 0
    stmt = insert(Candle).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["exchange", "symbol", "timeframe", "ts"],
        set_={c: stmt.excluded[c] for c in ("open", "high", "low", "close", "volume")},
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


class RedisDbSink:
    """Production sink: Redis for live data and events, Postgres/Timescale for candles."""

    def __init__(self, redis: Any, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.redis = redis
        self.sessionmaker = sessionmaker

    async def quote(self, quote: dict[str, Any]) -> None:
        payload = json.dumps(quote)
        await self.redis.hset(QUOTES_KEY, f"{quote['exchange']}:{quote['symbol']}", payload)
        await self.redis.publish(TICKS_CHANNEL, payload)

    async def candles(self, bars: list[Bar]) -> None:
        async with self.sessionmaker() as session:
            await upsert_bars(session, bars)
        for b in bars:
            payload = json.dumps(b.as_dict())
            await self.redis.set(candle_key(b.exchange, b.symbol, b.timeframe), payload)
            await self.redis.publish(CANDLES_CHANNEL, payload)


# ---------------------------------------------------------------- process

HISTORY_DAYS = 60  # 5m candles loaded at the start of each day: indicators + the Odds agent
SOURCE_CHECK_S = 30


async def backfill(
    adapter: Any, sessionmaker: Any, symbols: list[tuple[str, str]], now: datetime, log: Any
) -> int:
    """Load real 5m history (60 days) and today's 1m candles for every symbol."""
    from datetime import timedelta

    from app.brokers.base import DataPlanRequired
    from app.data.candles import Bar

    total = 0
    d = now.astimezone(IST).date()
    today_open = datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST)
    for exchange, symbol in symbols:
        for tf, start in (("5m", now - timedelta(days=HISTORY_DAYS)), ("1m", today_open)):
            if start >= now:
                continue
            try:
                df = await adapter.historical(exchange, symbol, tf, start, now)
            except DataPlanRequired:
                raise  # every symbol would fail the same way: tell the user once, clearly
            except Exception as exc:  # noqa: BLE001 - one symbol failing must not stop the rest
                log.warning("history failed", symbol=symbol, timeframe=tf, error=str(exc)[:200])
                continue
            bars = [
                Bar(
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=tf,
                    ts=r.ts.to_pydatetime(),
                    open=Decimal(str(r.open)),
                    high=Decimal(str(r.high)),
                    low=Decimal(str(r.low)),
                    close=Decimal(str(r.close)),
                    volume=int(r.volume),
                )
                for r in df.itertuples()
                # the candle still forming is left to the live feed
                if r.ts.to_pydatetime() + timedelta(minutes=int(tf[:-1])) <= now
            ]
            for i in range(0, len(bars), 2000):
                async with sessionmaker() as session:
                    total += await upsert_bars(session, bars[i : i + 2000])
    return total


async def run() -> None:  # pragma: no cover - long-running process, exercised manually
    import redis.asyncio as aioredis
    from sqlalchemy import delete

    from app.brokers.base import BrokerAuthError, DataPlanRequired
    from app.brokers.paper import PaperBroker
    from app.brokers.registry import create_adapter
    from app.brokers.service import load_credentials
    from app.core.config import get_settings
    from app.core.db import get_sessionmaker
    from app.core.logging import configure_logging, get_logger
    from app.data.source import (
        FEED_CHANNEL,
        FEED_KEY,
        FeedStatus,
        LiveSource,
        choose_source,
        in_feed_window,
        load_calendar,
        symbols_for,
    )
    from app.models import BrokerAccount, PlatformSetting

    settings = get_settings()
    configure_logging("INFO")
    log = get_logger("app.data.feed")
    redis = aioredis.from_url(settings.redis_url)
    sessionmaker = get_sessionmaker()
    processor = FeedProcessor(RedisDbSink(redis, sessionmaker))

    async def set_status(st: FeedStatus) -> None:
        await redis.set(FEED_KEY, st.as_json())
        await redis.publish(FEED_CHANNEL, st.as_json())
        log.info("feed status", source=st.source, state=st.state, message=st.message)

    async def switch_mode(mode: str) -> None:
        """Real and simulated prices must never mix: on switching, drop the other kind."""
        async with sessionmaker() as db:
            row = await db.get(PlatformSetting, "feed_mode")
            if row is not None and row.value == mode:
                return
            if row is None or row.value != mode:
                await db.execute(delete(Candle))  # candles of the other mode
                if row is None:
                    db.add(PlatformSetting(key="feed_mode", value=mode))
                else:
                    row.value = mode
                await db.commit()
        await redis.delete(QUOTES_KEY)
        log.info("feed mode switched, old candles cleared", mode=mode)

    async def run_simulator() -> None:
        await switch_mode("simulator")
        await set_status(
            FeedStatus("simulator", "simulated", "Simulated prices (no real source chosen)")
        )
        while True:
            broker = PaperBroker(seed=settings.feed_seed, tick_interval=1.0)
            symbols = [(i.exchange, i.symbol) for i in await broker.instruments()]
            try:
                async for tick in broker.stream(symbols):
                    await processor.handle(tick)
            except Exception:  # noqa: BLE001 - keep the feed alive
                log.exception("simulator error, restarting in 5s")
                await asyncio.sleep(5)

    async def run_live(src: LiveSource) -> None:
        await switch_mode("live")
        owner = str(src.user_id)
        name = src.connector.capitalize()
        loaded_day = None
        instruments = None
        while True:
            now = datetime.now(UTC)
            async with sessionmaker() as db:
                account = await db.get(BrokerAccount, src.account_id)
                creds = await load_credentials(db, account) if account else None
                symbols = await symbols_for(db, src.user_id)
                calendar = await load_calendar(db)
            if account is None or creds is None:
                await set_status(
                    FeedStatus(src.connector, "error", f"{name} account not found", owner)
                )
                await asyncio.sleep(60)
                continue
            adapter = create_adapter(src.broker, creds)
            try:
                if instruments is None or loaded_day != now.astimezone(IST).date():
                    await set_status(
                        FeedStatus(
                            src.connector, "connecting", f"Loading {name} instrument list…", owner
                        )
                    )
                    instruments = await adapter.instruments()
                else:
                    adapter.load_instrument_map(instruments)
                known = {(i.exchange, i.symbol) for i in instruments}
                ok = [s for s in symbols if s in known]
                missing = [f"{e}:{s}" for e, s in symbols if (e, s) not in known]
                if loaded_day != now.astimezone(IST).date():
                    await set_status(
                        FeedStatus(
                            src.connector,
                            "connecting",
                            f"Loading {HISTORY_DAYS} days of real candles…",
                            owner,
                            len(ok),
                            missing,
                        )
                    )
                    n = await backfill(adapter, sessionmaker, ok, now, log)
                    log.info("history loaded", candles=n, symbols=len(ok))
                    loaded_day = now.astimezone(IST).date()
                if not in_feed_window(now, calendar):
                    await set_status(
                        FeedStatus(
                            src.connector,
                            "closed",
                            f"Market closed (weekend or NSE holiday). Live {name} prices from "
                            "09:00 IST on the next trading day.",
                            owner,
                            len(ok),
                            missing,
                        )
                    )
                    await asyncio.sleep(SOURCE_CHECK_S)
                    continue
                await set_status(
                    FeedStatus(
                        src.connector,
                        "live",
                        f"Real-time prices from {name}",
                        owner,
                        len(ok),
                        missing,
                    )
                )
                async for tick in adapter.stream(ok):
                    await processor.handle(tick)
                    if not in_feed_window(datetime.now(UTC), calendar):
                        break
            except DataPlanRequired:
                await set_status(
                    FeedStatus(
                        src.connector,
                        "error",
                        f"Your {name} key works, but the account has no Data API plan, so {name} "
                        "sends no prices. Activate the Data API plan on web.dhan.co (DhanHQ APIs); "
                        "real prices start here within 5 minutes. No prices, no trades until then.",
                        owner,
                    )
                )
                await asyncio.sleep(300)
            except BrokerAuthError as exc:
                async with sessionmaker() as db:
                    acc = await db.get(BrokerAccount, src.account_id)
                    if acc is not None:
                        acc.status, acc.last_error = "expired", str(exc)[:300]
                        await db.commit()
                await set_status(
                    FeedStatus(
                        src.connector,
                        "error",
                        f"{name} rejected the key ({str(exc)[:120]}). Paste a new access token in "
                        "Settings and test it. No prices, no trades until then.",
                        owner,
                    )
                )
                await asyncio.sleep(60)
            except Exception as exc:  # noqa: BLE001 - keep the feed alive, never fake prices
                log.exception("live feed error")
                await set_status(
                    FeedStatus(
                        src.connector,
                        "error",
                        f"{name} feed error: {str(exc)[:160]}. Retrying.",
                        owner,
                    )
                )
                await asyncio.sleep(10)
            finally:
                await adapter.close()

    async def flusher() -> None:
        while True:
            await asyncio.sleep(5)
            try:
                await processor.flush(datetime.now(UTC))
            except Exception:  # noqa: BLE001
                log.exception("flush failed")

    flush_task = asyncio.create_task(flusher())
    current: LiveSource | None | str = "none-yet"
    task: asyncio.Task[None] | None = None
    try:
        while True:
            try:
                async with sessionmaker() as db:
                    desired = await choose_source(db)
            except Exception:  # noqa: BLE001
                log.exception("could not read the data source choice")
                desired = current if current != "none-yet" else None  # type: ignore[assignment]
            if desired != current or task is None or task.done():
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
                processor = FeedProcessor(RedisDbSink(redis, sessionmaker))
                current = desired
                task = asyncio.create_task(run_live(desired) if desired else run_simulator())
            await asyncio.sleep(SOURCE_CHECK_S)
    finally:
        flush_task.cancel()
        if task is not None:
            task.cancel()
        await redis.aclose()


def main() -> None:  # pragma: no cover
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
