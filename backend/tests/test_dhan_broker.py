"""Dhan adapter tests with mocked HTTP / WebSocket, shaped like the examples in Dhan's v2 docs."""

import io
import json
import struct
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.brokers import registry
from app.brokers.base import (
    BrokerAuthError,
    BrokerCredentials,
    BrokerError,
    BrokerNotSupported,
    Instrument,
    OrderRequest,
    RateLimited,
)
from app.brokers.dhan import (
    DhanBroker,
    parse_feed,
    parse_scrip_master,
    subscribe_messages,
)
from app.core.logging import clear_registered, configure_logging, get_logger

TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJkaGFuQ2xpZW50SWQiOiIxMTAwIn0.sigSIG123abcXYZ"
CLIENT = "1100001234"
CREDS = BrokerCredentials(
    trading={"client_id": CLIENT, "access_token": TOKEN},
    data={"client_id": CLIENT, "access_token": TOKEN},
)
SBIN = Instrument("dhan", "NSE", "EQ", "SBIN", "3045", "State Bank of India")
RELIANCE = Instrument("dhan", "NSE", "EQ", "RELIANCE", "2885", "Reliance Industries")

PROFILE = {
    "dhanClientId": CLIENT,
    "tokenValidity": "10/11/2026 09:15",
    "activeSegment": "Equity, Derivative",
    "ddpi": "Active",
    "mtf": "Deactive",
    "dataPlan": "Active",
    "dataValidity": "2026-12-31 00:00:00.0",
}
FUNDS = {
    "dhanClientId": CLIENT,
    "availabelBalance": 98440.0,
    "sodLimit": 113642.0,
    "collateralAmount": 0.0,
    "receiveableAmount": 0.0,
    "utilizedAmount": 15202.0,
    "blockedPayoutAmount": 0.0,
    "withdrawableBalance": 98310.0,
}


class FakeDhan:
    """Records requests and answers like the documented API."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get((request.method, request.url.path))
        if handler is None:
            return httpx.Response(404, json={"errorType": "x", "errorCode": "DH-910"})
        if callable(handler):
            return handler(request)
        status, body = handler
        return httpx.Response(status, json=body)

    def bodies(self, path: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]


def make(routes: dict, creds: BrokerCredentials = CREDS) -> tuple[DhanBroker, FakeDhan]:
    fake = FakeDhan(routes)
    broker = DhanBroker(creds, transport=httpx.MockTransport(fake))
    broker.load_instrument_map([SBIN, RELIANCE])
    return broker, fake


# ---------------------------------------------------------------- connection + funds


async def test_test_connection_ok() -> None:
    broker, fake = make(
        {("GET", "/v2/profile"): (200, PROFILE), ("GET", "/v2/fundlimit"): (200, FUNDS)}
    )
    report = await broker.test_connection()
    assert report.ok
    assert report.purpose_ok == {"trading": True, "data": True}
    assert report.funds is not None and report.funds.available == Decimal("98440.00")
    assert report.funds.used_margin == Decimal("15202.00")
    assert report.token_expires_at is not None
    assert report.token_expires_at.utcoffset() == timedelta(hours=5, minutes=30)
    req = fake.requests[0]
    assert req.url.host == "api.dhan.co"
    assert req.headers["access-token"] == TOKEN
    assert req.headers["Content-Type"] == "application/json"


async def test_data_plan_inactive_reported() -> None:
    broker, _ = make(
        {
            ("GET", "/v2/profile"): (200, {**PROFILE, "dataPlan": "Deactive"}),
            ("GET", "/v2/fundlimit"): (200, FUNDS),
        }
    )
    report = await broker.test_connection()
    assert not report.ok
    assert report.purpose_ok == {"trading": True, "data": False}
    assert "Data API plan" in report.message


async def test_expired_token_is_auth_error() -> None:
    err = {
        "errorType": "Invalid_Authentication",
        "errorCode": "DH-901",
        "errorMessage": "Client ID or user generated access token is invalid or expired.",
    }
    broker, _ = make({("GET", "/v2/profile"): (401, err), ("GET", "/v2/fundlimit"): (401, err)})
    report = await broker.test_connection()
    assert not report.ok and report.purpose_ok == {"trading": False, "data": False}
    assert "DH-901" in report.message
    assert TOKEN not in report.message
    with pytest.raises(BrokerAuthError):
        await broker.funds()


async def test_rate_limit_error() -> None:
    broker, _ = make(
        {("GET", "/v2/fundlimit"): (429, {"errorType": "Rate_Limit", "errorCode": "DH-904"})}
    )
    with pytest.raises(RateLimited):
        await broker.funds()


async def test_only_trading_key_is_tested_when_no_data_key() -> None:
    creds = BrokerCredentials(trading={"client_id": CLIENT, "access_token": TOKEN})
    broker, _ = make(
        {("GET", "/v2/profile"): (200, PROFILE), ("GET", "/v2/fundlimit"): (200, FUNDS)}, creds
    )
    report = await broker.test_connection()
    assert report.purpose_ok == {"trading": True}


async def test_missing_credentials() -> None:
    broker = DhanBroker(BrokerCredentials(trading={"client_id": CLIENT}))
    with pytest.raises(BrokerAuthError, match="access_token"):
        await broker.funds()
    empty = await DhanBroker().test_connection()
    assert not empty.ok


async def test_orders_not_supported_yet() -> None:
    broker, _ = make({})
    broker.live_enabled = True
    req = OrderRequest(uuid.uuid4(), "NSE", "SBIN", "BUY", 1)
    with pytest.raises(BrokerNotSupported):
        await broker.place_order(req)


# ---------------------------------------------------------------- historical


def chart(start_epoch: int, n: int, step: int, base: float = 800.0) -> dict:
    return {
        "open": [base + i for i in range(n)],
        "high": [base + i + 2.5 for i in range(n)],
        "low": [base + i - 1.25 for i in range(n)],
        "close": [base + i + 1.1 for i in range(n)],
        "volume": [1000 + i for i in range(n)],
        "timestamp": [start_epoch + i * step for i in range(n)],
        "open_interest": [0] * n,
    }


async def test_intraday_history_request_and_parse() -> None:
    start = datetime(2026, 11, 9, 3, 45, tzinfo=UTC)  # 09:15 IST
    end = start + timedelta(minutes=15)
    t0 = int(start.timestamp())
    broker, fake = make({("POST", "/v2/charts/intraday"): (200, chart(t0, 4, 300))})
    df = await broker.historical("NSE", "SBIN", "5m", start, end)

    (body,) = fake.bodies("/v2/charts/intraday")
    assert body == {
        "securityId": "3045",
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "interval": 5,
        "fromDate": "2026-11-09 09:15:00",
        "toDate": "2026-11-09 09:30:00",
    }
    assert len(df) == 3  # 4th bar is at `end`, outside [start, end)
    assert df["ts"].iloc[0] == start
    assert df["close"].iloc[0] == Decimal("801.10")
    assert isinstance(df["open"].iloc[0], Decimal)
    assert df["volume"].tolist() == [1000, 1001, 1002]


async def test_intraday_history_split_into_90_day_chunks() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=200)
    broker, fake = make({("POST", "/v2/charts/intraday"): (200, chart(0, 0, 60))})
    df = await broker.historical("NSE", "SBIN", "15m", start, end)
    assert df.empty
    assert len(fake.bodies("/v2/charts/intraday")) == 3  # 90 + 90 + 20 days


async def test_daily_history_uses_exclusive_to_date() -> None:
    start = datetime(2026, 11, 2, tzinfo=UTC)
    end = datetime(2026, 11, 7, tzinfo=UTC)
    broker, fake = make({("POST", "/v2/charts/historical"): (200, chart(0, 0, 86400))})
    await broker.historical("NSE", "RELIANCE", "1d", start, end)
    (body,) = fake.bodies("/v2/charts/historical")
    assert body["securityId"] == "2885"
    assert body["fromDate"] == "2026-11-02"
    assert body["toDate"] == "2026-11-08"


async def test_malformed_history_rejected() -> None:
    bad = chart(0, 3, 60)
    bad["close"] = bad["close"][:2]
    broker, _ = make({("POST", "/v2/charts/intraday"): (200, bad)})
    with pytest.raises(BrokerError, match="malformed"):
        await broker.historical(
            "NSE", "SBIN", "1m", datetime(1970, 1, 1, tzinfo=UTC), datetime(1970, 1, 2, tzinfo=UTC)
        )


async def test_unknown_symbol() -> None:
    broker, _ = make({})
    with pytest.raises(BrokerError, match="unknown instrument"):
        await broker.historical("NSE", "NOPE", "5m", datetime.now(UTC), datetime.now(UTC))


# ---------------------------------------------------------------- scrip master

SCRIP_CSV = """SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,SM_SYMBOL_NAME
BSE,C,1026077,FUTCUR,0,USDINR-28Aug2024-FUT,1.0,USDINR AUG FUT,2024-08-28 14:30:00,-0.01000,XX,0.2500,M,FUTCUR,,USDINR
NSE,E,11536,EQUITY,0,TCS,1.0,Tata Consultancy Services,,,,10.0000,NA,ES,EQ,TATA CONSULTANCY SERV LT
NSE,E,2885,EQUITY,0,RELIANCE,1.0,Reliance Industries,,,,10.0000,NA,ES,EQ,RELIANCE INDUSTRIES LTD
NSE,E,3045,EQUITY,0,SBIN,1.0,State Bank of India,,,,5.0000,NA,ES,EQ,STATE BANK OF INDIA
NSE,E,99999,EQUITY,0,SOMEBOND,1.0,Some Bond,,,,1.0000,NA,DBT,SG,SOME BOND
"""


def test_parse_scrip_master() -> None:
    result = {i.symbol: i for i in parse_scrip_master(SCRIP_CSV)}
    assert set(result) == {"TCS", "RELIANCE", "SBIN"}
    sbin = result["SBIN"]
    assert sbin.broker_token == "3045"
    assert sbin.exchange == "NSE" and sbin.segment == "EQ"
    assert sbin.tick_size == Decimal("0.05")  # 5 paise
    assert result["TCS"].tick_size == Decimal("0.1")
    assert sbin.name == "State Bank of India"


async def test_instruments_download_loads_map() -> None:
    def scrip(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SCRIP_CSV)

    fake = FakeDhan({("GET", "/api-data/api-scrip-master.csv"): scrip})
    broker = DhanBroker(CREDS, transport=httpx.MockTransport(fake))
    inst = await broker.instruments()
    assert len(inst) == 3
    assert fake.requests[0].url.host == "images.dhan.co"
    assert broker.security_id("NSE", "TCS") == "11536"


# ---------------------------------------------------------------- feed packets


def header(code: int, segment: int, sid: int, length: int) -> bytes:
    return struct.pack("<BhBi", code, length, segment, sid)


def quote_packet(sid: int, ltp: float, volume: int, ltq: int = 10) -> bytes:
    return header(4, 1, sid, 50) + struct.pack(
        "<fhifiiiffff", ltp, ltq, 1762660000, ltp - 0.5, volume, 500, 700, 800.0, 0.0, 812.0, 795.5
    )


def ticker_packet(sid: int, ltp: float) -> bytes:
    return header(2, 1, sid, 16) + struct.pack("<fi", ltp, 1762660000)


def disconnect_packet(reason: int) -> bytes:
    return header(50, 1, 0, 10) + struct.pack("<h", reason)


def test_parse_quote_packet() -> None:
    (pkt,) = parse_feed(quote_packet(3045, 801.35, 123456))
    assert pkt["code"] == 4 and pkt["segment"] == 1 and pkt["security_id"] == 3045
    assert pkt["ltp"] == Decimal("801.35")
    assert pkt["volume"] == 123456
    assert pkt["last_qty"] == 10
    assert pkt["high"] == Decimal("812.00") and pkt["low"] == Decimal("795.50")


def test_parse_multiple_and_truncated_packets() -> None:
    data = ticker_packet(3045, 800.05) + quote_packet(2885, 2900.5, 99) + b"\x04\x00"
    pkts = parse_feed(data)
    assert [p["code"] for p in pkts] == [2, 4]
    assert pkts[0]["ltp"] == Decimal("800.05")
    assert parse_feed(quote_packet(1, 1.0, 1)[:30]) == []  # truncated: nothing misread


def test_parse_disconnect_and_unknown() -> None:
    (pkt,) = parse_feed(disconnect_packet(807))
    assert pkt["code"] == 50 and pkt["reason"] == 807
    assert parse_feed(header(99, 1, 1, 8)) == []


def test_subscribe_messages_batched_by_100() -> None:
    inst = [("NSE_EQ", str(i)) for i in range(250)]
    msgs = subscribe_messages(inst, 17)
    assert [m["InstrumentCount"] for m in msgs] == [100, 100, 50]
    assert msgs[0]["RequestCode"] == 17
    assert msgs[0]["InstrumentList"][0] == {"ExchangeSegment": "NSE_EQ", "SecurityId": "0"}


# ---------------------------------------------------------------- feed stream


class FakeWS:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = frames
        self.sent: list[dict] = []
        self.closed = False

    async def send(self, msg: str) -> None:
        self.sent.append(json.loads(msg))

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for f in self.frames:
            yield f


async def test_stream_yields_ticks_for_subscribed_symbols() -> None:
    ws = FakeWS([quote_packet(3045, 801.35, 1000), quote_packet(77777, 5.0, 1)])
    urls: list[str] = []

    async def connect(url: str) -> FakeWS:
        urls.append(url)
        return ws

    broker = DhanBroker(CREDS, ws_connect=connect)
    broker.load_instrument_map([SBIN, RELIANCE])
    ticks = [t async for t in broker.stream([("NSE", "SBIN"), ("NSE", "RELIANCE")])]

    assert len(ticks) == 1  # unknown security id ignored
    t = ticks[0]
    assert (t.exchange, t.symbol, t.ltp, t.volume) == ("NSE", "SBIN", Decimal("801.35"), 1000)
    assert t.ts.tzinfo is not None
    assert urls[0].startswith("wss://api-feed.dhan.co?version=2&token=")
    assert f"clientId={CLIENT}" in urls[0] and urls[0].endswith("authType=2")
    sub = ws.sent[0]
    assert sub["RequestCode"] == 17 and sub["InstrumentCount"] == 2
    assert {"ExchangeSegment": "NSE_EQ", "SecurityId": "3045"} in sub["InstrumentList"]
    assert ws.sent[-1] == {"RequestCode": 12}
    assert ws.closed


async def test_stream_disconnect_code_raises_auth_error() -> None:
    async def connect(url: str) -> FakeWS:
        return FakeWS([disconnect_packet(807)])

    broker = DhanBroker(CREDS, ws_connect=connect)
    broker.load_instrument_map([SBIN])
    with pytest.raises(BrokerAuthError, match="807"):
        async for _ in broker.stream([("NSE", "SBIN")]):
            pass


def test_feed_url_token_masked_in_logs() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    broker = DhanBroker(CREDS)
    get_logger().info("connecting", url=broker.feed_url())
    assert TOKEN not in stream.getvalue()
    clear_registered()


# ---------------------------------------------------------------- registry


def test_dhan_in_registry_with_form_fields() -> None:
    dhan = {b["key"]: b for b in registry.available()}["dhan"]
    assert dhan["display_name"] == "Dhan"
    for purpose in ("trading", "data"):
        names = [f["name"] for f in dhan["credential_fields"][purpose]]
        assert names == ["client_id", "access_token"]
        token_field = dhan["credential_fields"][purpose][1]
        assert token_field["secret"] is True and token_field["help"]
    assert isinstance(registry.create_adapter("dhan", CREDS), DhanBroker)


PLAN_ERR = {
    "errorType": "Invalid_Authentication",
    "errorCode": "DH-902",
    "errorMessage": "This API requires a Data APIs Plan. Current plan: Free Plan",
}


async def test_missing_data_plan_is_its_own_error_not_an_expired_token() -> None:
    from app.brokers.base import DataPlanRequired

    broker, _ = make({("POST", "/v2/charts/intraday"): (401, PLAN_ERR)})
    with pytest.raises(DataPlanRequired, match="Data APIs Plan"):
        await broker._request("POST", "/charts/intraday", "data", json_body={})
    other = {**PLAN_ERR, "errorMessage": "User has no access to this API"}
    broker, _ = make({("POST", "/v2/charts/intraday"): (401, other)})
    with pytest.raises(BrokerAuthError) as exc:
        await broker._request("POST", "/charts/intraday", "data", json_body={})
    assert not isinstance(exc.value, DataPlanRequired)


async def test_trading_key_without_data_plan_passes_with_a_note() -> None:
    trading_only = BrokerCredentials(trading=dict(CREDS.trading))
    broker, _ = make(
        {
            ("GET", "/v2/profile"): (200, {**PROFILE, "dataPlan": "Deactive"}),
            ("GET", "/v2/fundlimit"): (200, FUNDS),
        },
        trading_only,
    )
    report = await broker.test_connection()
    assert report.ok and report.purpose_ok == {"trading": True}
    assert "Data API plan is not active" in report.message
