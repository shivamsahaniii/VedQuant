from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers.base import Tick
from app.data.candles import IST, Bar
from app.data.feed import FeedProcessor, QuoteBook, upsert_bars
from app.models import Candle

D = Decimal
T0 = datetime(2026, 11, 9, 9, 15, tzinfo=IST)


def tick(sec: int, price: str, cum: int = 0, sym: str = "SBIN") -> Tick:
    return Tick("NSE", sym, T0 + timedelta(seconds=sec), D(price), cum, 0)


class FakeSink:
    def __init__(self) -> None:
        self.quotes: list[dict[str, Any]] = []
        self.bars: list[Bar] = []

    async def quote(self, quote: dict[str, Any]) -> None:
        self.quotes.append(quote)

    async def candles(self, bars: list[Bar]) -> None:
        self.bars += bars


def test_quote_book_day_stats_and_reset() -> None:
    q = QuoteBook()
    q.update(tick(0, "800"))
    q.update(tick(5, "810"))
    last = q.update(tick(9, "796"))
    assert (last["open"], last["high"], last["low"]) == ("800", "810", "796")
    assert last["change"] == "-4" and last["change_pct"] == "-0.50"
    next_day = Tick("NSE", "SBIN", T0 + timedelta(days=1), D("790"), 0, 0)
    fresh = q.update(next_day)
    assert fresh["open"] == "790" and fresh["change"] == "0"


async def test_processor_sends_quotes_and_closed_candles() -> None:
    sink = FakeSink()
    p = FeedProcessor(sink, ("1m", "5m"))
    for s in range(0, 301, 15):  # 09:15:00 -> 09:20:00
        await p.handle(tick(s, str(800 + s // 15), cum=100 * (s + 1)))
    assert len(sink.quotes) == 21
    assert [b.timeframe for b in sink.bars].count("1m") == 5
    assert [b.timeframe for b in sink.bars].count("5m") == 1
    await p.flush(T0 + timedelta(minutes=30))
    assert [b.timeframe for b in sink.bars].count("1m") == 6  # the 09:20 bar, flushed


async def test_upsert_bars_is_idempotent(db: AsyncSession) -> None:
    ts = T0.astimezone(UTC)
    bar = Bar("NSE", "SBIN", "5m", ts, D("800"), D("805"), D("799"), D("803"), 1000)
    assert await upsert_bars(db, [bar]) == 1
    updated = Bar("NSE", "SBIN", "5m", ts, D("800"), D("806"), D("799"), D("804"), 1200)
    await upsert_bars(db, [updated])
    assert await db.scalar(select(func.count()).select_from(Candle)) == 1
    c = await db.scalar(select(Candle))
    assert c is not None and c.close == D("804") and c.volume == 1200
    assert await upsert_bars(db, []) == 0
