import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import fakeredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.feed import QUOTES_KEY
from app.engine.worker import CONTEXT_KEY, refresh_context, stocks_from_quotes
from app.models import Candle

NOW = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)  # 13:30 IST


def q(sym: str, open_: str, ltp: str) -> str:
    return json.dumps({"exchange": "NSE", "symbol": sym, "open": open_, "ltp": ltp})


def test_stocks_from_quotes_skips_index() -> None:
    raw = {"NSE:NIFTY50": q("NIFTY50", "24000", "24100"), "NSE:SBIN": q("SBIN", "800", "810")}
    assert stocks_from_quotes(raw) == {"SBIN": (800.0, 810.0)}


async def test_refresh_context_uses_5m_and_stores_in_redis(db: AsyncSession) -> None:
    start = NOW - timedelta(minutes=5 * 40)
    for i in range(40):
        c = Decimal(24000 + 10 * i)
        db.add(
            Candle(
                exchange="NSE",
                symbol="NIFTY50",
                timeframe="5m",
                ts=start + timedelta(minutes=5 * i),
                open=c - 5,
                high=c + 8,
                low=c - 8,
                close=c,
                volume=0,
            )
        )
    await db.commit()
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    for i in range(10):
        await redis.hset(QUOTES_KEY, f"NSE:S{i}", q(f"S{i}", "100", "101" if i < 8 else "99"))

    ctx = await refresh_context(db, redis, NOW)
    assert ctx.timeframe == "5m" and ctx.trend == "up" and ctx.bias == "bullish"
    stored = json.loads(await redis.get(CONTEXT_KEY))
    assert stored["summary"] == ctx.summary and stored["breadth"]["up"] == 8


async def test_refresh_context_warms_up_on_1m(db: AsyncSession) -> None:
    for i in range(5):
        c = Decimal(24000 + i)
        db.add(
            Candle(
                exchange="NSE",
                symbol="NIFTY50",
                timeframe="1m",
                ts=NOW - timedelta(minutes=5 - i),
                open=c,
                high=c + 1,
                low=c - 1,
                close=c,
                volume=0,
            )
        )
    await db.commit()
    ctx = await refresh_context(db, fakeredis.FakeAsyncRedis(decode_responses=True), NOW)
    assert ctx.timeframe == "1m" and ctx.warming_up
