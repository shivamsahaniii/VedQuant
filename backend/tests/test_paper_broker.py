import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

import pytest

from app.brokers import registry
from app.brokers.base import (
    BrokerAdapter,
    BrokerAuthError,
    BrokerCredentials,
    BrokerNotSupported,
    FieldSpec,
    LiveTradingBlocked,
    OrderAck,
    OrderChanges,
    OrderRejected,
    OrderRequest,
)
from app.brokers.paper import PaperBroker, _Pos, apply_fill, round_to_tick
from app.core.config import get_settings

D = Decimal
EX = "NSE"


def order(side="BUY", qty=10, order_type="MARKET", price=None, trigger=None, sym="SBIN", ref=None):
    return OrderRequest(
        order_ref=ref or uuid.uuid4(),
        exchange=EX,
        symbol=sym,
        side=side,
        qty=qty,
        order_type=order_type,
        price=D(price) if price is not None else None,
        trigger_price=D(trigger) if trigger is not None else None,
    )


@pytest.fixture
def broker() -> PaperBroker:
    b = PaperBroker(starting_cash=D("100000"), slippage_bps=D("10"), seed=1)
    b.set_price(EX, "SBIN", D("800"))
    return b


# ---------------------------------------------------------------- orders


async def test_market_buy_fills_with_slippage(broker: PaperBroker) -> None:
    ack = await broker.place_order(order("BUY", 10))
    assert ack.status == "FILLED"
    st = await broker.order_status(ack.broker_order_id)
    assert st.avg_price == D("800.80")  # 800 * 1.001, rounded up to 0.05
    assert st.filled_qty == 10
    (pos,) = await broker.positions()
    assert pos.qty == 10 and pos.avg_price == D("800.80")


async def test_market_sell_slippage_is_against_you(broker: PaperBroker) -> None:
    ack = await broker.place_order(order("SELL", 10))
    st = await broker.order_status(ack.broker_order_id)
    assert st.avg_price == D("799.20")
    (pos,) = await broker.positions()
    assert pos.qty == -10


async def test_round_trip_books_realised_pnl_and_frees_margin(broker: PaperBroker) -> None:
    await broker.place_order(order("BUY", 10))  # 800.80
    broker.set_price(EX, "SBIN", D("810"))
    await broker.place_order(order("SELL", 10))  # 810 * 0.999 = 809.19 -> floor 809.15
    (pos,) = await broker.positions()
    assert pos.qty == 0
    assert pos.realised_pnl == D("83.50")  # (809.15 - 800.80) * 10
    funds = await broker.funds()
    assert funds.used_margin == 0
    assert funds.available == D("100083.50")


async def test_unrealised_pnl_follows_price(broker: PaperBroker) -> None:
    await broker.place_order(order("BUY", 10))
    broker.set_price(EX, "SBIN", D("790.80"))
    (pos,) = await broker.positions()
    assert pos.unrealised_pnl == D("-100.00")


async def test_limit_buy_waits_then_fills_at_market(broker: PaperBroker) -> None:
    ack = await broker.place_order(order("BUY", 5, "LIMIT", price="795"))
    assert ack.status == "OPEN"
    broker.set_price(EX, "SBIN", D("796"))
    assert (await broker.order_status(ack.broker_order_id)).status == "OPEN"
    broker.set_price(EX, "SBIN", D("794.50"))
    st = await broker.order_status(ack.broker_order_id)
    assert st.status == "FILLED" and st.avg_price == D("794.50")


async def test_sl_m_sell_triggers_on_drop(broker: PaperBroker) -> None:
    await broker.place_order(order("BUY", 10))
    ack = await broker.place_order(order("SELL", 10, "SL-M", trigger="790"))
    assert ack.status == "TRIGGER_PENDING"
    broker.set_price(EX, "SBIN", D("795"))
    assert (await broker.order_status(ack.broker_order_id)).status == "TRIGGER_PENDING"
    broker.set_price(EX, "SBIN", D("789"))
    st = await broker.order_status(ack.broker_order_id)
    assert st.status == "FILLED"
    assert st.avg_price == D("788.20")  # 789 * 0.999 floored to tick


async def test_sl_becomes_limit_after_trigger(broker: PaperBroker) -> None:
    ack = await broker.place_order(order("BUY", 1, "SL", price="812", trigger="810"))
    broker.set_price(EX, "SBIN", D("815"))  # triggered, but above limit 812
    assert (await broker.order_status(ack.broker_order_id)).status == "OPEN"
    broker.set_price(EX, "SBIN", D("811"))
    st = await broker.order_status(ack.broker_order_id)
    assert st.status == "FILLED" and st.avg_price == D("811")


async def test_order_without_price_waits_for_first_tick() -> None:
    b = PaperBroker()
    ack = await b.place_order(order("BUY", 1, sym="TCS"))
    assert ack.status == "OPEN"
    b.set_price(EX, "TCS", D("4000"))
    assert (await b.order_status(ack.broker_order_id)).status == "FILLED"


async def test_same_order_ref_never_places_twice(broker: PaperBroker) -> None:
    ref = uuid.uuid4()
    a1 = await broker.place_order(order("BUY", 10, ref=ref))
    a2 = await broker.place_order(order("BUY", 10, ref=ref))
    assert a1.broker_order_id == a2.broker_order_id
    (pos,) = await broker.positions()
    assert pos.qty == 10


async def test_insufficient_funds_rejected() -> None:
    b = PaperBroker(starting_cash=D("1000"), slippage_bps=D(0))
    b.set_price(EX, "SBIN", D("800"))
    ok = await b.place_order(order("BUY", 1))
    assert ok.status == "FILLED"
    too_big = await b.place_order(order("BUY", 1))
    assert too_big.status == "REJECTED"
    assert "Insufficient funds" in too_big.message
    # Closing a position is always allowed.
    assert (await b.place_order(order("SELL", 1))).status == "FILLED"


async def test_cancel_and_modify(broker: PaperBroker) -> None:
    ack = await broker.place_order(order("BUY", 5, "LIMIT", price="700"))
    mod = await broker.modify_order(ack.broker_order_id, OrderChanges(price=D("800")))
    assert mod.status == "FILLED"  # now marketable

    ack2 = await broker.place_order(order("BUY", 5, "LIMIT", price="700"))
    await broker.cancel_order(ack2.broker_order_id)
    assert (await broker.order_status(ack2.broker_order_id)).status == "CANCELLED"
    with pytest.raises(OrderRejected):
        await broker.cancel_order(ack2.broker_order_id)
    with pytest.raises(OrderRejected):
        await broker.modify_order(ack.broker_order_id, OrderChanges(price=D("1")))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"qty": 0},
        {"order_type": "LIMIT"},  # no price
        {"order_type": "SL-M"},  # no trigger
        {"side": "HOLD"},
    ],
)
def test_order_request_validation(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        order(**kwargs)


def test_order_request_rejects_float_price() -> None:
    with pytest.raises(TypeError):
        OrderRequest(uuid.uuid4(), EX, "SBIN", "BUY", 1, "LIMIT", price=800.5)  # type: ignore[arg-type]


# ---------------------------------------------------------------- position maths


@pytest.mark.parametrize(
    "start, signed, price, expected",
    [
        (_Pos(), 10, D(100), _Pos(10, D(100))),
        (_Pos(10, D(100)), 10, D(110), _Pos(20, D(105))),
        (_Pos(10, D(100)), -4, D(110), _Pos(6, D(100), D(40))),
        (_Pos(10, D(100)), -10, D(90), _Pos(0, D(0), D(-100))),
        (_Pos(10, D(100)), -15, D(110), _Pos(-5, D(110), D(100))),
        (_Pos(-10, D(100)), 10, D(90), _Pos(0, D(0), D(100))),
    ],
)
def test_apply_fill(start: _Pos, signed: int, price: Decimal, expected: _Pos) -> None:
    assert apply_fill(start, signed, price) == expected


@pytest.mark.parametrize(
    "price, up, expected",
    [
        (D("800.81"), True, D("800.85")),
        (D("800.81"), False, D("800.80")),
        (D("800.83"), None, D("800.85")),
    ],
)
def test_round_to_tick(price: Decimal, up: bool | None, expected: Decimal) -> None:
    assert round_to_tick(price, up=up) == expected


# ---------------------------------------------------------------- data


async def test_demo_stream_ticks() -> None:
    b = PaperBroker(seed=42, tick_interval=0)
    syms = [(EX, "RELIANCE"), (EX, "TCS")]
    ticks = []
    async for t in b.stream(syms):
        ticks.append(t)
        if len(ticks) == 20:
            break
    assert {t.symbol for t in ticks} == {"RELIANCE", "TCS"}
    assert all(t.ltp % D("0.05") == 0 and t.ltp > 0 for t in ticks)
    assert all(t.ts.tzinfo is not None for t in ticks)
    rel = [t for t in ticks if t.symbol == "RELIANCE"]
    assert all(b2.volume > b1.volume for b1, b2 in zip(rel, rel[1:], strict=False))
    assert b.last_price(EX, "RELIANCE") == rel[-1].ltp


async def test_demo_stream_is_deterministic_with_seed() -> None:
    async def first(seed: int) -> list[Decimal]:
        b = PaperBroker(seed=seed, tick_interval=0)
        out = []
        async for t in b.stream([(EX, "INFY")]):
            out.append(t.ltp)
            if len(out) == 5:
                return out
        return out

    assert await first(7) == await first(7)


async def test_historical_candles() -> None:
    b = PaperBroker()
    # Fri 6 Nov 2026 .. Mon 9 Nov 2026 (IST); weekend must be skipped.
    start = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
    end = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
    df = await b.historical(EX, "SBIN", "5m", start, end)
    assert len(df) == 2 * 75  # 75 five-minute bars per session, 2 weekdays
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert df["ts"].is_monotonic_increasing
    assert {ts.weekday() for ts in df["ts"]} == {4, 0}
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()
    assert isinstance(df["close"].iloc[0], Decimal)
    # First bar opens 09:15 IST = 03:45 UTC.
    assert df["ts"].iloc[0] == datetime(2026, 11, 6, 3, 45, tzinfo=UTC)
    # Deterministic.
    again = await b.historical(EX, "SBIN", "5m", start, end)
    assert df.equals(again)


async def test_instruments_and_connection() -> None:
    b = PaperBroker()
    inst = await b.instruments()
    assert len(inst) == 11 and all(i.exchange == "NSE" for i in inst)
    assert inst[0].symbol == "NIFTY50" and inst[0].segment == "IDX"
    report = await b.test_connection()
    assert report.ok and report.funds is not None


# ---------------------------------------------------------------- registry + live gate


def test_registry_lists_paper() -> None:
    brokers = {b["key"]: b for b in registry.available()}
    assert brokers["paper"]["is_paper"] is True
    assert brokers["paper"]["credential_fields"] == {"trading": [], "data": []}
    assert isinstance(registry.create_adapter("paper"), PaperBroker)
    with pytest.raises(registry.UnknownBroker):
        registry.create_adapter("nope")


class _FakeLiveBroker(BrokerAdapter):
    key: ClassVar[str] = "fake_live"
    display_name: ClassVar[str] = "Fake live broker"
    supports = frozenset({"trading"})
    credential_fields = {"trading": [FieldSpec("api_key", "API key")], "data": []}
    sent: ClassVar[list[OrderRequest]] = []

    async def _place_order(self, req: OrderRequest) -> OrderAck:
        self.sent.append(req)
        return OrderAck(req.order_ref, "X1", "OPEN")


@pytest.fixture
def platform_live(monkeypatch: pytest.MonkeyPatch):
    def set_mode(mode: str) -> None:
        monkeypatch.setattr(get_settings(), "trading_mode", mode)

    yield set_mode


@pytest.mark.parametrize(
    "platform_mode, user_live, allowed",
    [("paper", False, False), ("paper", True, False), ("live", False, False), ("live", True, True)],
)
async def test_live_order_needs_platform_and_user_live(
    platform_live, platform_mode: str, user_live: bool, allowed: bool
) -> None:
    platform_live(platform_mode)
    _FakeLiveBroker.sent.clear()
    b = _FakeLiveBroker(BrokerCredentials(trading={"api_key": "k" * 20}), live_enabled=user_live)
    if allowed:
        await b.place_order(order())
        assert len(_FakeLiveBroker.sent) == 1
    else:
        with pytest.raises(LiveTradingBlocked):
            await b.place_order(order())
        assert _FakeLiveBroker.sent == []


def test_paper_mode_is_platform_default() -> None:
    assert get_settings().trading_mode == "paper"


async def test_missing_credentials_and_unsupported() -> None:
    b = _FakeLiveBroker()
    with pytest.raises(BrokerAuthError) as exc:
        b.require("trading")
    assert "api_key" in str(exc.value)
    with pytest.raises(BrokerNotSupported):
        await b.positions()


def test_credentials_repr_hides_values() -> None:
    c = BrokerCredentials(trading={"api_key": "super-secret-value-123"})
    assert "super-secret" not in repr(c)
    assert "api_key" in repr(c)
