"""Paper trading on real prices: Dhan indices + day stats, source choice, feed privacy, candles."""

import json
import struct
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import login_limiter
from app.api.market import aggregate
from app.brokers.base import Instrument, Tick
from app.brokers.dhan import DhanBroker, parse_scrip_master
from app.core import security
from app.core.db import get_session
from app.core.redis import set_redis
from app.data.feed import QUOTES_KEY, QuoteBook
from app.data.source import (
    FEED_KEY,
    FeedStatus,
    can_see_feed,
    choose_source,
    in_feed_window,
    symbols_for,
)
from app.engine.nse import TradingCalendar
from app.engine.pipeline import running_strategies
from app.main import app
from app.models import BrokerAccount, Candle, Strategy, User, UserSetting, WatchItem
from tests.test_dhan_broker import CREDS, SBIN, FakeWS, header, quote_packet

IST = ZoneInfo("Asia/Kolkata")
PW = "a-strong-password-1"

# Rows copied from Dhan's scrip master (2026-11-09).
INDEX_CSV = """SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,SM_SYMBOL_NAME
NSE,I,13,INDEX,0,NIFTY,1.0,Nifty 50,0001-01-01,,XX,0.0500,,INDEX,X,NIFTY
NSE,I,21,INDEX,0,INDIA VIX,1.0,India VIX,0001-01-01,,XX,0.0500,,INDEX,X,INDIA VIX
NSE,I,25,INDEX,0,BANKNIFTY,1.0,Nifty Bank,0001-01-01,,XX,0.0500,,INDEX,X,BANKNIFTY
BSE,I,51,INDEX,0,SENSEX,1.0,Sensex,0001-01-01,,XX,0.0100,,INDEX,X,SENSEX
NSE,E,3045,EQUITY,0,SBIN,1.0,State Bank of India,,,,5.0000,NA,ES,EQ,STATE BANK OF INDIA
"""  # noqa: E501


def at(h, m, day=date(2026, 11, 10)):
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(UTC)


# ---------------------------------------------------------------- Dhan adapter


def test_scrip_master_includes_indices_with_our_symbols():
    by = {(i.exchange, i.symbol): i for i in parse_scrip_master(INDEX_CSV)}
    assert by[("NSE", "NIFTY50")].broker_token == "13" and by[("NSE", "NIFTY50")].segment == "IDX"
    assert ("NSE", "INDIAVIX") in by and ("NSE", "BANKNIFTY") in by and ("BSE", "SENSEX") in by
    assert by[("NSE", "SBIN")].segment == "EQ"


async def test_index_streams_on_idx_segment_with_prev_close():
    nifty = Instrument("dhan", "NSE", "IDX", "NIFTY50", "13", "Nifty 50", 1, D("0.05"))
    prev = header(6, 0, 13, 16) + struct.pack("<fi", 24000.0, 0)
    quote = header(4, 0, 13, 50) + struct.pack(
        "<fhifiiiffff", 24120.5, 0, 1762660000, 0.0, 0, 0, 0, 24050.0, 0.0, 24150.0, 24010.0
    )
    ws = FakeWS([prev + quote, quote_packet(3045, 801.35, 1000)])

    async def connect(url):
        return ws

    broker = DhanBroker(CREDS, ws_connect=connect)
    broker.load_instrument_map([nifty, SBIN])
    ticks = [t async for t in broker.stream([("NSE", "NIFTY50"), ("NSE", "SBIN")])]
    assert {"ExchangeSegment": "IDX_I", "SecurityId": "13"} in ws.sent[0]["InstrumentList"]
    n = ticks[0]
    assert (n.symbol, n.ltp, n.prev_close) == ("NIFTY50", D("24120.5"), D("24000"))
    assert (n.day_open, n.day_high, n.day_low) == (D("24050"), D("24150"), D("24010"))


def test_quote_change_is_from_previous_close_and_exchange_open():
    book = QuoteBook()
    q = book.update(
        Tick(
            "NSE",
            "SBIN",
            at(11, 0),
            D("810"),
            day_open=D("805"),
            day_high=D("812"),
            day_low=D("801"),
            prev_close=D("800"),
        )
    )
    assert (q["open"], q["high"], q["low"]) == ("805", "812", "801")
    assert q["change"] == "10" and q["change_pct"] == "1.25" and q["prev_close"] == "800"
    sim = book.update(Tick("NSE", "TCS", at(11, 0), D("4100")))  # simulator: tracks its own
    assert sim["open"] == "4100" and sim["prev_close"] is None


# ---------------------------------------------------------------- source choice


def test_feed_window_and_privacy():
    assert in_feed_window(at(9, 0)) and in_feed_window(at(15, 34))
    assert not in_feed_window(at(8, 59)) and not in_feed_window(at(15, 35))
    assert not in_feed_window(at(10, 0, date(2026, 11, 14)))  # Saturday
    assert not in_feed_window(at(10, 0), TradingCalendar(["2026-11-10"]))
    owner = uuid.uuid4()
    real = FeedStatus("dhan", "live", owner_user_id=str(owner))
    assert can_see_feed(real, owner) and not can_see_feed(real, uuid.uuid4())
    assert can_see_feed(FeedStatus("simulator", "simulated"), uuid.uuid4())
    assert can_see_feed(None, uuid.uuid4())


async def _user(db, email="a@example.com", role="user"):
    u = User(email=email, password_hash=security.hash_password("long-enough-pw"), role=role)
    db.add(u)
    await db.flush()
    return u


async def test_choose_source_needs_a_real_choice_and_an_account(db: AsyncSession):
    a = await _user(db)
    assert await choose_source(db) is None  # nobody chose a real source: simulator
    db.add(
        UserSetting(
            user_id=a.id,
            key="connections",
            value={"data_sources": {"stocks": "dhan", "indices": "dhan"}},
        )
    )
    await db.flush()
    assert await choose_source(db) is None  # chose Dhan but has no Dhan account
    acc = BrokerAccount(user_id=a.id, broker="dhan", label="Main", status="connected")
    db.add(acc)
    await db.flush()
    src = await choose_source(db)
    assert src.user_id == a.id and src.account_id == acc.id and src.broker == "dhan"
    acc.status = "expired"  # still chosen: the feed then reports the expired token loudly
    await db.flush()
    assert (await choose_source(db)).account_id == acc.id


async def test_symbols_for_owner(db: AsyncSession):
    a = await _user(db)
    db.add_all(
        [
            WatchItem(
                user_id=a.id, asset_class="stocks", exchange="NSE", symbol="SBIN", position=0
            ),
            WatchItem(user_id=a.id, asset_class="crypto", exchange="BINANCE", symbol="BTCUSDT"),
            Strategy(
                user_id=a.id,
                name="ORB",
                section="intraday",
                template_key="orb",
                status="paper",
                params={"symbols": ["TCS", "SBIN"]},
            ),
            Strategy(
                user_id=a.id,
                name="Off",
                section="intraday",
                template_key="orb",
                status="paused",
                params={"symbols": ["INFY"]},
            ),
        ]
    )
    await db.flush()
    assert await symbols_for(db, a.id) == [("NSE", "NIFTY50"), ("NSE", "SBIN"), ("NSE", "TCS")]


async def test_real_feed_trades_only_its_owners_strategies(db: AsyncSession):
    a, b = await _user(db), await _user(db, "b@example.com")
    for u in (a, b):
        db.add(
            Strategy(
                user_id=u.id,
                name="ORB",
                section="intraday",
                template_key="orb",
                status="paper",
                params={"timeframe": "5m"},
            )
        )
    await db.flush()
    assert len(await running_strategies(db, "SBIN", "5m")) == 2
    only = await running_strategies(db, "SBIN", "5m", a.id)
    assert [s.user_id for s in only] == [a.id]


# ---------------------------------------------------------------- candles + API privacy


def test_15m_candles_are_built_from_5m():
    rows = [
        Candle(
            exchange="NSE",
            symbol="SBIN",
            timeframe="5m",
            ts=at(9, 15 + 5 * i),
            open=D(100 + i),
            high=D(101 + i),
            low=D(99 + i),
            close=D(100.5 + i),
            volume=10,
        )
        for i in range(6)
    ]
    bars = aggregate(rows, "15m")
    assert len(bars) == 2 and bars[0]["ts"] == at(9, 15) and bars[1]["ts"] == at(9, 30)
    assert (bars[0]["open"], bars[0]["high"], bars[0]["low"], bars[0]["close"]) == (
        D(100),
        D(103),
        D(99),
        D("102.5"),
    )
    assert bars[0]["volume"] == 30


@pytest.fixture
async def client(db: AsyncSession):
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    set_redis(redis)

    async def _session():
        yield db

    app.dependency_overrides[get_session] = _session
    login_limiter.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, redis
    app.dependency_overrides.clear()
    set_redis(None)


async def test_someone_elses_real_feed_is_not_shared(client):
    c, redis = client
    tokens = []
    for email in ("a@example.com", "b@example.com"):
        r = await c.post("/auth/signup", json={"email": email, "password": PW})
        tokens.append({"Authorization": f"Bearer {r.json()['access_token']}"})
    owner = (await c.get("/auth/me", headers=tokens[0])).json()["id"]
    await redis.set(
        FEED_KEY, FeedStatus("dhan", "live", "Real-time prices from Dhan", owner).as_json()
    )
    await redis.hset(
        QUOTES_KEY, "NSE:SBIN", json.dumps({"exchange": "NSE", "symbol": "SBIN", "ltp": "801.35"})
    )
    assert len((await c.get("/market/quotes", headers=tokens[0])).json()) == 1
    assert (await c.get("/market/feed", headers=tokens[0])).json()["state"] == "live"
    assert (await c.get("/market/quotes", headers=tokens[1])).json() == []
    assert (await c.get("/market/feed", headers=tokens[1])).json()["state"] == "unavailable"
    wl = (await c.get("/markets/watchlist", headers=tokens[1])).json()["items"]
    assert all(i["quote"] is None for i in wl)


async def test_watchlist_shows_real_prices_to_the_owner(client, db):
    c, redis = client
    r = await c.post("/auth/signup", json={"email": "a@example.com", "password": PW})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    uid = (await c.get("/auth/me", headers=h)).json()["id"]
    db.add(BrokerAccount(user_id=uuid.UUID(uid), broker="dhan", label="Main", status="connected"))
    await db.commit()
    assert (
        await c.put("/connectors/preferences", headers=h, json={"data_sources": {"stocks": "dhan"}})
    ).status_code == 200
    await redis.set(
        FEED_KEY,
        FeedStatus(
            "dhan", "live", "Real-time prices from Dhan", uid, missing=["NSE:AXISBANK"]
        ).as_json(),
    )
    await redis.hset(
        QUOTES_KEY, "NSE:SBIN", json.dumps({"exchange": "NSE", "symbol": "SBIN", "ltp": "801.35"})
    )
    by = {i["symbol"]: i for i in (await c.get("/markets/watchlist", headers=h)).json()["items"]}
    assert by["SBIN"]["data"]["state"] == "live" and by["SBIN"]["quote"]["ltp"] == "801.35"
    assert by["AXISBANK"]["data"]["label"] == "Not found"
    assert by["TCS"]["data"]["state"] == "waiting"
    # NIFTY 50 still set to the simulator, which is off while a real feed runs.
    assert by["NIFTY50"]["data"]["label"] == "Simulator off"


async def test_backfill_stores_history_but_not_the_forming_candle(db: AsyncSession):
    import contextlib

    import pandas as pd
    from sqlalchemy import select

    from app.data.feed import backfill

    now = at(10, 2)

    class FakeAdapter:
        calls: list = []

        async def historical(self, exchange, symbol, tf, start, end):
            self.calls.append((symbol, tf))
            step = 5 if tf == "5m" else 1
            ts = [at(9, 15) + pd.Timedelta(minutes=step * i) for i in range(48 // step)]
            return pd.DataFrame(
                {"ts": ts, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10}
            )

    @contextlib.asynccontextmanager
    async def sessionmaker():
        yield db

    class Log:
        def warning(self, *a, **k):
            pass

    adapter = FakeAdapter()
    await backfill(adapter, sessionmaker, [("NSE", "SBIN")], now, Log())
    assert adapter.calls == [("SBIN", "5m"), ("SBIN", "1m")]
    five = (await db.scalars(select(Candle.ts).where(Candle.timeframe == "5m"))).all()
    assert max(five) == at(9, 55)  # the 10:00 candle is still forming at 10:02: live feed's job
    one = (await db.scalars(select(Candle.ts).where(Candle.timeframe == "1m"))).all()
    assert max(one) == at(10, 1)  # the 10:01 one-minute candle closed exactly at 10:02


async def test_holidays_come_from_the_platform_setting(db: AsyncSession):
    from app.data.source import load_calendar
    from app.models import PlatformSetting

    assert (await load_calendar(db)).is_trading_day(date(2026, 11, 10))
    db.add(PlatformSetting(key="nse_holidays", value=["2026-11-10"]))
    await db.flush()
    cal = await load_calendar(db)
    assert not cal.is_trading_day(date(2026, 11, 10)) and cal.is_trading_day(date(2026, 11, 11))
    assert not in_feed_window(at(10, 0), cal)


async def test_backfill_stops_at_once_without_a_data_plan(db: AsyncSession):
    import contextlib

    from app.brokers.base import DataPlanRequired
    from app.data.feed import backfill

    class NoPlan:
        calls = 0

        async def historical(self, *a):
            self.calls += 1
            raise DataPlanRequired("Dhan DH-902: This API requires a Data APIs Plan")

    @contextlib.asynccontextmanager
    async def sessionmaker():
        yield db

    adapter = NoPlan()
    with pytest.raises(DataPlanRequired):
        await backfill(adapter, sessionmaker, [("NSE", "SBIN"), ("NSE", "TCS")], at(10, 2), None)
    assert adapter.calls == 1  # not once per symbol and timeframe
