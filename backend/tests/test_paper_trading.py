"""End to end on the database: agent chain -> signal -> paper trade -> stop/target/square-off."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import fakeredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.data.feed import QUOTES_KEY
from app.engine.pipeline import OddsPools, on_candle
from app.engine.worker import CONTEXT_KEY, handle_candle, handle_square_off, handle_tick
from app.models import Candle, Order, Signal, Strategy, Trade, User
from app.orders.paper import OpenRequest, market_fill, on_price, open_trade

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 10)  # Tuesday


def at(h, m, s=0):
    return datetime(DAY.year, DAY.month, DAY.day, h, m, s, tzinfo=IST).astimezone(UTC)


BULL = json.dumps(
    {
        "trend": "up",
        "strength": "moderate",
        "volatility": "normal",
        "bias": "bullish",
        "summary": "Uptrend",
        "warming_up": False,
    }
)
BEAR = json.dumps(
    {
        "trend": "down",
        "strength": "strong",
        "volatility": "normal",
        "bias": "bearish",
        "summary": "Downtrend",
        "warming_up": False,
    }
)
BAR = {"exchange": "NSE", "symbol": "SBIN", "timeframe": "5m"}


async def make_user(db, email="a@example.com"):
    u = User(email=email, password_hash=security.hash_password("long-enough-pw"))
    db.add(u)
    await db.flush()
    return u


async def make_strategy(db, user, mode="auto", **params):
    s = Strategy(
        user_id=user.id,
        name=f"ORB {mode}",
        section="intraday",
        template_key="orb",
        status="paper",
        params={"timeframe": "5m", "symbols": ["SBIN"], "mode": mode, **params},
    )
    db.add(s)
    await db.flush()
    return s


async def orb_day(db):
    """09:15-09:25 = range 817.50-822.00; the 09:30 candle closes above it at 823.50."""
    rows = [
        (9, 15, 820, 822, 818, 821),
        (9, 20, 821, 821, 817.5, 819),
        (9, 25, 819, 821.5, 818, 820),
        (9, 30, 820, 824, 819.5, 823.5),
    ]
    for h, m, o, hi, lo, c in rows:
        db.add(
            Candle(
                exchange="NSE",
                symbol="SBIN",
                timeframe="5m",
                ts=at(h, m),
                open=D(o),
                high=D(hi),
                low=D(lo),
                close=D(c),
                volume=1000,
            )
        )
    await db.flush()


async def run_chain(db, ltp="823.60", ctx=BULL, now=None):
    return await on_candle(
        db, BAR, now=now or at(9, 35, 20), ltp=D(ltp), context_raw=ctx, pools=OddsPools()
    )


# ---------------------------------------------------------------- the chain


async def test_auto_strategy_takes_a_paper_trade(db: AsyncSession):
    user = await make_user(db)
    strat = await make_strategy(db, user)
    await orb_day(db)

    [sig] = await run_chain(db)
    assert sig.status == "taken", sig.status_reason
    assert sig.plan["stop"] == "819.75" and sig.plan["stop_rule"] == "or_mid"
    assert sig.plan["target"] == "831.30"
    assert sig.risk["qty"] == 40 and sig.risk["sized_by"] == "position size"
    assert sig.odds["available"] is False  # no past sessions yet: said, not guessed

    trade = await db.scalar(select(Trade).where(Trade.user_id == user.id))
    assert trade.status == "open" and trade.qty == 40 and trade.strategy_id == strat.id
    assert trade.entry_price == D("824.05")  # 823.60 + 0.05 % slippage, rounded up to the tick
    roles = set((await db.scalars(select(Order.role).where(Order.trade_id == trade.id))).all())
    assert roles == {"entry", "stop", "target"}

    assert await run_chain(db) == []  # same setup again: no second decision, no second trade


async def test_suggest_mode_does_not_trade(db: AsyncSession):
    user = await make_user(db)
    await make_strategy(db, user, mode="suggest")
    await orb_day(db)
    [sig] = await run_chain(db)
    assert sig.status == "suggested" and "suggest-only" in sig.status_reason
    assert await db.scalar(select(func.count()).select_from(Trade)) == 0


async def test_market_mood_against_the_rule_skips(db: AsyncSession):
    user = await make_user(db)
    await make_strategy(db, user)
    await orb_day(db)
    [sig] = await run_chain(db, ctx=BEAR)
    assert sig.status == "skipped" and "Market mood" in sig.status_reason


async def test_chasing_and_late_data_are_skipped(db: AsyncSession):
    user = await make_user(db)
    await make_strategy(db, user)
    await orb_day(db)
    [sig] = await run_chain(db, ltp="830.00")
    assert sig.status == "skipped" and "already ran" in sig.status_reason


async def test_each_user_gets_their_own_signals_and_trades(db: AsyncSession):
    a, b = await make_user(db, "a@example.com"), await make_user(db, "b@example.com")
    await make_strategy(db, a)
    await make_strategy(db, b, mode="suggest")
    await orb_day(db)
    sigs = await run_chain(db)
    assert {(s.user_id, s.status) for s in sigs} == {(a.id, "taken"), (b.id, "suggested")}
    trades = (await db.scalars(select(Trade))).all()
    assert [t.user_id for t in trades] == [a.id]


async def test_paused_or_other_symbol_strategies_do_not_run(db: AsyncSession):
    user = await make_user(db)
    s = await make_strategy(db, user)
    s.status = "paused"
    await make_strategy(db, user, mode="suggest", symbols=["TCS"])
    await orb_day(db)
    assert await run_chain(db) == []


# ---------------------------------------------------------------- the paper broker


async def _open(db, side="buy", ltp="1000", stop="990", target="1020"):
    user = await make_user(db)
    req = OpenRequest(
        user_id=user.id,
        strategy_id=None,
        signal_id=None,
        section="intraday",
        exchange="NSE",
        symbol="TCS",
        side=side,
        qty=10,
        stop=D(stop),
        target=D(target),
        ref="test:1",
        tick=D("0.05"),
    )
    return user, req, await open_trade(db, req, D(ltp), at(10, 0))


def test_market_fill_slips_against_you():
    assert market_fill("buy", D("1000"), D("0.05")) == D("1000.50")
    assert market_fill("sell", D("1000"), D("0.05")) == D("999.50")


async def test_open_is_idempotent(db: AsyncSession):
    _, req, t1 = await _open(db)
    t2 = await open_trade(db, req, D("1005"), at(10, 1))
    assert t1.id == t2.id and await db.scalar(select(func.count()).select_from(Trade)) == 1


async def test_target_hit_books_net_pnl_and_cancels_the_stop(db: AsyncSession):
    _, _, t = await _open(db)
    assert await on_price(db, "NSE", "TCS", D("1010"), at(10, 5)) == []
    [closed] = await on_price(db, "NSE", "TCS", D("1020.40"), at(10, 30))
    assert closed.exit_reason == "target" and closed.exit_price == D("1020")  # limit price
    assert closed.gross_pnl == (D("1020") - D("1000.50")) * 10
    assert closed.net_pnl == closed.gross_pnl - closed.charges and closed.charges > 0
    legs = {o.role: o.status for o in (await db.scalars(select(Order))).all()}
    assert legs == {"entry": "filled", "target": "filled", "stop": "cancelled"}


async def test_gap_through_the_stop_fills_worse_than_the_stop(db: AsyncSession):
    _, _, t = await _open(db)
    [closed] = await on_price(db, "NSE", "TCS", D("980"), at(11, 0))  # gapped 10 below the stop
    assert closed.exit_reason == "stop" and closed.exit_price == D("979.50")
    assert -closed.gross_pnl > t.max_loss  # the plan said 105; a gap costs more


async def test_short_trade(db: AsyncSession):
    _, _, t = await _open(db, side="sell", stop="1010", target="980")
    [closed] = await on_price(db, "NSE", "TCS", D("979"), at(11, 0))
    assert closed.exit_reason == "target" and closed.gross_pnl == (D("999.50") - D("980")) * 10


# ---------------------------------------------------------------- engine handlers


async def test_square_off_at_15_15(db: AsyncSession):
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    await _open(db)
    await redis.hset(
        QUOTES_KEY, "NSE:TCS", json.dumps({"exchange": "NSE", "symbol": "TCS", "ltp": "1005"})
    )
    assert await handle_square_off(db, redis, at(15, 14)) == 0
    assert await handle_square_off(db, redis, at(15, 15, 30)) == 1
    t = await db.scalar(select(Trade))
    assert t.exit_reason == "square_off" and t.exit_price == D("1004.45")  # 1004.4975 down
    assert "exit" in set((await db.scalars(select(Order.role))).all())


async def test_handlers_publish_and_close(db: AsyncSession):
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    user = await make_user(db)
    await make_strategy(db, user)
    await orb_day(db)
    await redis.set(CONTEXT_KEY, BULL)
    await redis.hset(
        QUOTES_KEY, "NSE:SBIN", json.dumps({"exchange": "NSE", "symbol": "SBIN", "ltp": "823.60"})
    )
    [p] = await handle_candle(db, redis, BAR, at(9, 35, 20), OddsPools())
    assert p["status"] == "taken" and p["user_id"] == str(user.id)
    n = await handle_tick(
        db, redis, {"exchange": "NSE", "symbol": "SBIN", "ltp": "819.00"}, at(9, 50)
    )
    assert n == 1
    t = await db.scalar(select(Trade))
    assert t.exit_reason == "stop" and t.net_pnl < 0
    assert await db.scalar(select(func.count()).select_from(Signal)) == 1
