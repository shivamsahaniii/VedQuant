"""Dhan (DhanHQ API v2) adapter.

Built from the official docs, read 2026-11-09: https://dhanhq.co/docs/v2/
Phase 1 scope: connection test, funds, instruments, historical candles, live feed.
Order methods come in Phase 4 (they need a whitelisted static IP, per Dhan's docs).

Auth (Phase 1): the user generates a 24-hour access token at web.dhan.co
(My Profile -> Access DhanHQ APIs) and pastes it with their Client ID.
TODO(phase 3/4): API key + secret consent login (auth.dhan.co) so the token can be renewed
without pasting a new one every day.

Every point the docs leave open is marked TODO(verify).
"""

from __future__ import annotations

import csv
import io
import json
import struct
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from app.brokers.base import (
    AsyncRateLimiter,
    BrokerAdapter,
    BrokerAuthError,
    BrokerCredentials,
    BrokerError,
    Capability,
    ConnectionReport,
    DataPlanRequired,
    FieldSpec,
    Funds,
    Instrument,
    Purpose,
    RateLimited,
    Tick,
    Timeframe,
)
from app.core.logging import get_logger, register_secret

API_BASE = "https://api.dhan.co/v2"
FEED_URL = "wss://api-feed.dhan.co"
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
IST = ZoneInfo("Asia/Kolkata")

_log = get_logger("app.brokers.dhan")

# Exchange segment names (API/JSON) and numeric codes (binary feed header). Annexure.
SEGMENT_CODES: dict[str, int] = {
    "IDX_I": 0,
    "NSE_EQ": 1,
    "NSE_FNO": 2,
    "NSE_CURRENCY": 3,
    "BSE_EQ": 4,
    "MCX_COMM": 5,
    "BSE_CURRENCY": 7,
    "BSE_FNO": 8,
}
SEGMENT_NAMES = {v: k for k, v in SEGMENT_CODES.items()}
# Our (exchange, segment) -> Dhan exchangeSegment. Cash equity and indices.
_EQ_SEGMENT = {"NSE": "NSE_EQ", "BSE": "BSE_EQ"}
INDEX_SEGMENT = "IDX_I"
# Dhan index trading symbol -> Vedquant symbol (checked against the scrip master 2026-11-09:
# NSE,I,13,INDEX,...,NIFTY = Nifty 50; 25 BANKNIFTY; 27 FINNIFTY; 29 NIFTYIT; 21 INDIA VIX;
# BSE,I,51 SENSEX). Other indices keep Dhan's symbol with spaces removed.
_INDEX_SYMBOLS = {"NIFTY": "NIFTY50", "INDIA VIX": "INDIAVIX"}

# Intraday chart intervals (minutes). 1h maps to 60. Dhan also has 25m, unused here.
_INTRADAY_INTERVAL = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
_INTRADAY_MAX_DAYS = 90  # "only 90 days of data can be polled at once"

# Feed request codes (annexure).
REQ_DISCONNECT = 12
REQ_SUBSCRIBE_QUOTE = 17
REQ_UNSUBSCRIBE_QUOTE = 18
MAX_INSTRUMENTS_PER_MESSAGE = 100
MAX_INSTRUMENTS_PER_CONNECTION = 5000

# Feed response codes (annexure).
RESP_TICKER = 2
RESP_QUOTE = 4
RESP_PREV_CLOSE = 6
RESP_DISCONNECT = 50

# Little-endian. Header: uint8 response code, int16 message length, uint8 segment, int32 id.
_HEADER = struct.Struct("<BhBi")  # 8 bytes
_TICKER = struct.Struct("<fi")  # LTP float32, LTT int32            -> 16-byte packet
# LTP, LTQ, LTT, ATP, volume, total sell qty, total buy qty, open, close, high, low -> 50 bytes
_QUOTE = struct.Struct("<fhifiiiffff")
_DISCONNECT = struct.Struct("<h")
_PACKET_SIZE = {RESP_TICKER: 16, RESP_QUOTE: 50, RESP_PREV_CLOSE: 16, RESP_DISCONNECT: 10}

# Feed disconnect / data API error codes that mean "credentials problem".
_AUTH_DATA_CODES = {806, 807, 808, 809, 810}


def _dec(value: Any, places: int = 2) -> Decimal:
    """Broker floats -> Decimal, rounded (float32 prices carry noise)."""
    return Decimal(f"{float(value):.{places}f}")


class DhanBroker(BrokerAdapter):
    key: ClassVar[str] = "dhan"
    display_name: ClassVar[str] = "Dhan"
    supports: ClassVar[frozenset[Capability]] = frozenset({"data", "historical"})
    auth_type = "api_key"
    docs_url = "https://dhanhq.co/docs/v2/"
    credential_fields: ClassVar[dict[Purpose, list[FieldSpec]]] = {
        "trading": [
            FieldSpec(
                "client_id",
                "Client ID",
                secret=False,
                help="Your Dhan Client ID, shown under My Profile on web.dhan.co.",
            ),
            FieldSpec(
                "access_token",
                "Access token",
                help="web.dhan.co > My Profile > Access DhanHQ APIs > generate Access Token. "
                "Valid for 24 hours.",
            ),
        ],
        "data": [
            FieldSpec(
                "client_id",
                "Client ID",
                secret=False,
                help="Your Dhan Client ID, shown under My Profile on web.dhan.co.",
            ),
            FieldSpec(
                "access_token",
                "Access token",
                help="Same kind of token as for trading. Live data needs Dhan's Data API "
                "subscription to be active on the account.",
            ),
        ],
    }

    def __init__(
        self,
        credentials: BrokerCredentials | None = None,
        *,
        live_enabled: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        ws_connect: Callable[[str], Awaitable[Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(credentials, live_enabled=live_enabled)
        for purpose in ("trading", "data"):
            register_secret(self.credentials.for_purpose(purpose).get("access_token"))
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._ws_connect = ws_connect
        self._clock = clock or (lambda: datetime.now(UTC))
        # Rate limits from the docs (per second): data 5, non-trading 20, orders 10.
        self._data_limiter = AsyncRateLimiter(5, 1.0)
        self._api_limiter = AsyncRateLimiter(20, 1.0)
        self._ids: dict[tuple[str, str], str] = {}  # (exchange, symbol) -> securityId
        self._indices: set[tuple[str, str]] = set()  # instruments that are indices (IDX_I)

    # ------------------------------------------------------------ HTTP

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=API_BASE, timeout=httpx.Timeout(20.0), transport=self._transport
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _purpose_for_data(self) -> Purpose:
        """Data calls use the data key; fall back to the trading key if only that exists."""
        return "data" if self.credentials.data.get("access_token") else "trading"

    async def _request(
        self,
        method: str,
        path: str,
        purpose: Purpose,
        *,
        json_body: dict[str, Any] | None = None,
        limiter: AsyncRateLimiter | None = None,
    ) -> Any:
        creds = self.require(purpose)
        await (limiter or self._api_limiter).acquire()
        headers = {
            "access-token": creds["access_token"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            resp = await self._client().request(method, path, headers=headers, json=json_body)
        except httpx.HTTPError as exc:
            raise BrokerError(f"Dhan: network error on {path}: {type(exc).__name__}") from None
        return self._parse(resp, path)

    @staticmethod
    def _parse(resp: httpx.Response, path: str) -> Any:
        try:
            body = resp.json() if resp.content else None
        except ValueError:
            body = None
        if resp.is_success:
            return body
        code = str(body.get("errorCode", "")) if isinstance(body, dict) else ""
        msg = str(body.get("errorMessage", "")) if isinstance(body, dict) else ""
        text = f"Dhan {code or resp.status_code} on {path}: {msg or resp.reason_phrase}"
        if code == "DH-902" and "plan" in msg.lower():
            raise DataPlanRequired(text)  # valid token, no Data APIs subscription
        if code in ("DH-901", "DH-902") or resp.status_code == 401:
            raise BrokerAuthError(text)
        if code == "DH-904" or resp.status_code == 429:
            raise RateLimited(text)
        raise BrokerError(text)

    # ------------------------------------------------------------ connection

    async def test_connection(self) -> ConnectionReport:
        """Checks each purpose that has credentials: profile (token valid), funds (trading)."""
        purpose_ok: dict[str, bool] = {}
        notes: list[str] = []
        info: list[str] = []  # not failures, but worth telling the user
        funds: Funds | None = None
        expires: datetime | None = None

        for purpose in ("trading", "data"):
            if not self.credentials.for_purpose(purpose):
                continue
            try:
                profile = await self._request("GET", "/profile", purpose)
                expires = _parse_token_validity(profile.get("tokenValidity")) or expires
                ok = True
                if purpose == "data" and profile.get("dataPlan") != "Active":
                    ok = False
                    notes.append("data: Data API plan is not active on this Dhan account")
                if purpose == "trading":
                    funds = await self.funds()
                    if (
                        not self.credentials.for_purpose("data")
                        and profile.get("dataPlan") != "Active"
                    ):
                        info.append(
                            "Data API plan is not active, so prices stay simulated until you "
                            "activate it on web.dhan.co"
                        )
                purpose_ok[purpose] = ok
            except BrokerError as exc:
                purpose_ok[purpose] = False
                notes.append(f"{purpose}: {exc}")

        if not purpose_ok:
            return ConnectionReport(ok=False, message="No Dhan credentials added yet")
        ok = all(purpose_ok.values())
        message = "Connected to Dhan" if ok else "; ".join(notes)
        if ok and info:
            message += ". " + "; ".join(info) + "."
        return ConnectionReport(
            ok=ok, message=message, purpose_ok=purpose_ok, funds=funds, token_expires_at=expires
        )

    async def funds(self) -> Funds:
        data = await self._request("GET", "/fundlimit", "trading")
        return Funds(
            available=_dec(data.get("availabelBalance", 0)),  # spelling as in Dhan's docs
            used_margin=_dec(data.get("utilizedAmount", 0)),
            total=_dec(data.get("sodLimit", 0)),
        )

    # ------------------------------------------------------------ instruments

    async def instruments(self) -> list[Instrument]:
        """NSE/BSE cash equities from Dhan's public scrip master (~28 MB CSV).

        TODO(phase 6): derivatives (NSE_FNO) and indices.
        """
        try:
            resp = await self._client().get(SCRIP_MASTER_URL, timeout=120)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BrokerError(f"Dhan: could not download instrument list: {exc}") from None
        result = parse_scrip_master(resp.text)
        self.load_instrument_map(result)
        return result

    def load_instrument_map(self, instruments: Iterable[Instrument]) -> None:
        """Teach the adapter symbol -> securityId (usually from our `instruments` table)."""
        for i in instruments:
            if i.broker == self.key:
                self._ids[(i.exchange, i.symbol)] = i.broker_token
                if i.segment == "IDX":
                    self._indices.add((i.exchange, i.symbol))

    def segment(self, exchange: str, symbol: str) -> str:
        """Dhan exchangeSegment for one of our instruments: IDX_I for indices, else cash equity."""
        if (exchange, symbol) in self._indices:
            return INDEX_SEGMENT
        seg = _EQ_SEGMENT.get(exchange)
        if seg is None:
            raise BrokerError(f"Dhan: exchange {exchange} not supported yet")
        return seg

    def security_id(self, exchange: str, symbol: str) -> str:
        try:
            return self._ids[(exchange, symbol)]
        except KeyError:
            raise BrokerError(
                f"Dhan: unknown instrument {exchange}:{symbol} (instrument list not loaded?)"
            ) from None

    # ------------------------------------------------------------ historical

    async def historical(
        self, exchange: str, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        segment = self.segment(exchange, symbol)
        base = {
            "securityId": self.security_id(exchange, symbol),
            "exchangeSegment": segment,
            # TODO(verify): "INDEX" as the instrument type for IDX_I charts (docs list it in
            # the instrument annexure; not yet tried against the live API).
            "instrument": "INDEX" if segment == INDEX_SEGMENT else "EQUITY",
        }
        purpose = self._purpose_for_data()
        frames: list[pd.DataFrame] = []

        if timeframe == "1d":
            body = {
                **base,
                "fromDate": start.astimezone(IST).date().isoformat(),
                # toDate is non-inclusive per the docs.
                "toDate": (end.astimezone(IST).date() + timedelta(days=1)).isoformat(),
            }
            data = await self._request(
                "POST", "/charts/historical", purpose, json_body=body, limiter=self._data_limiter
            )
            frames.append(_candles_frame(data))
        else:
            interval = _INTRADAY_INTERVAL[timeframe]
            for chunk_start, chunk_end in _chunks(start, end, _INTRADAY_MAX_DAYS):
                body = {
                    **base,
                    "interval": interval,
                    # TODO(verify): docs show "YYYY-MM-DD HH:MM:SS" without a zone; IST assumed.
                    "fromDate": chunk_start.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                    "toDate": chunk_end.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                }
                data = await self._request(
                    "POST", "/charts/intraday", purpose, json_body=body, limiter=self._data_limiter
                )
                frames.append(_candles_frame(data))

        df = pd.concat(frames, ignore_index=True) if frames else _candles_frame({})
        if df.empty:
            return df
        df = df.drop_duplicates("ts").sort_values("ts")
        return df[(df["ts"] >= start) & (df["ts"] < end)].reset_index(drop=True)

    # ------------------------------------------------------------ live feed

    def feed_url(self) -> str:
        creds = self.require(self._purpose_for_data())
        return (
            f"{FEED_URL}?version=2&token={creds['access_token']}"
            f"&clientId={creds['client_id']}&authType=2"
        )

    async def stream(self, instruments: list[tuple[str, str]]) -> AsyncIterator[Tick]:  # type: ignore[override]
        """Quote-mode live ticks. Raises BrokerError on disconnect; the caller reconnects."""
        if len(instruments) > MAX_INSTRUMENTS_PER_CONNECTION:
            raise BrokerError(f"Dhan: max {MAX_INSTRUMENTS_PER_CONNECTION} instruments per feed")
        reverse: dict[tuple[int, int], tuple[str, str]] = {}
        wanted: list[tuple[str, str]] = []
        prev_close: dict[tuple[str, str], Decimal] = {}
        for exchange, symbol in instruments:
            seg = self.segment(exchange, symbol)
            sid = self.security_id(exchange, symbol)
            reverse[(SEGMENT_CODES[seg], int(sid))] = (exchange, symbol)
            wanted.append((seg, sid))

        connect = self._ws_connect or _default_ws_connect
        ws = await connect(self.feed_url())
        try:
            for msg in subscribe_messages(wanted, REQ_SUBSCRIBE_QUOTE):
                await ws.send(json.dumps(msg))
            async for raw in ws:
                if isinstance(raw, str):  # feed is binary; ignore any text frames
                    continue
                for pkt in parse_feed(raw):
                    if pkt["code"] == RESP_DISCONNECT:
                        reason = pkt.get("reason")
                        err = BrokerAuthError if reason in _AUTH_DATA_CODES else BrokerError
                        raise err(f"Dhan feed disconnected (code {reason})")
                    key = reverse.get((pkt["segment"], pkt["security_id"]))
                    if key is None:
                        continue
                    if pkt["code"] == RESP_PREV_CLOSE:
                        prev_close[key] = pkt["prev_close"]
                        continue
                    if pkt["code"] not in (RESP_QUOTE, RESP_TICKER):
                        continue
                    yield Tick(
                        exchange=key[0],
                        symbol=key[1],
                        # TODO(verify): LTT epoch's time base is not stated in the docs, so
                        # the receive time (UTC) is used as the tick time for now.
                        ts=self._clock(),
                        ltp=pkt["ltp"],
                        volume=pkt.get("volume", 0),
                        last_qty=pkt.get("last_qty", 0),
                        day_open=pkt.get("open") or None,
                        day_high=pkt.get("high") or None,
                        day_low=pkt.get("low") or None,
                        prev_close=prev_close.get(key) or pkt.get("close") or None,
                    )
        finally:
            try:
                await ws.send(json.dumps({"RequestCode": REQ_DISCONNECT}))
            except Exception:  # noqa: BLE001,S110 - socket may already be closed
                pass
            await ws.close()


# ---------------------------------------------------------------- pure helpers (tested)


def subscribe_messages(
    instruments: list[tuple[str, str]], request_code: int
) -> list[dict[str, Any]]:
    """Feed subscribe JSON, max 100 instruments per message (per the docs)."""
    out = []
    for i in range(0, len(instruments), MAX_INSTRUMENTS_PER_MESSAGE):
        batch = instruments[i : i + MAX_INSTRUMENTS_PER_MESSAGE]
        out.append(
            {
                "RequestCode": request_code,
                "InstrumentCount": len(batch),
                "InstrumentList": [
                    {"ExchangeSegment": seg, "SecurityId": str(sid)} for seg, sid in batch
                ],
            }
        )
    return out


def parse_feed(data: bytes) -> list[dict[str, Any]]:
    """Decode one binary feed message (one or more packets, little-endian).

    TODO(verify): whether one message can hold several packets, and the exact meaning of
    the header 'message length'. Packets are split using the documented fixed sizes.
    """
    packets: list[dict[str, Any]] = []
    offset = 0
    while offset + _HEADER.size <= len(data):
        code, _length, segment, security_id = _HEADER.unpack_from(data, offset)
        size = _PACKET_SIZE.get(code)
        if size is None or offset + size > len(data):
            break  # unknown or truncated packet: stop, never misread the rest
        body = offset + _HEADER.size
        pkt: dict[str, Any] = {"code": code, "segment": segment, "security_id": security_id}
        if code == RESP_TICKER:
            ltp, ltt = _TICKER.unpack_from(data, body)
            pkt.update(ltp=_dec(ltp), ltt=ltt)
        elif code == RESP_QUOTE:
            ltp, ltq, ltt, atp, vol, sell_q, buy_q, o, c, h, low = _QUOTE.unpack_from(data, body)
            pkt.update(
                ltp=_dec(ltp),
                last_qty=ltq,
                ltt=ltt,
                atp=_dec(atp),
                volume=vol,
                total_sell_qty=sell_q,
                total_buy_qty=buy_q,
                open=_dec(o),
                close=_dec(c),
                high=_dec(h),
                low=_dec(low),
            )
        elif code == RESP_PREV_CLOSE:
            prev_close, prev_oi = _TICKER.unpack_from(data, body)
            pkt.update(prev_close=_dec(prev_close), prev_oi=prev_oi)
        elif code == RESP_DISCONNECT:
            (reason,) = _DISCONNECT.unpack_from(data, body)
            pkt.update(reason=reason)
        packets.append(pkt)
        offset += size
    return packets


def parse_scrip_master(text: str) -> list[Instrument]:
    """Dhan compact scrip master CSV -> NSE/BSE cash equities (series EQ/BE) and indices.

    Tick size in the CSV is in paise (e.g. SBIN "5.0000" = Rs 0.05), checked 2026-11-09.
    """
    out: list[Instrument] = []
    for row in csv.DictReader(io.StringIO(text)):
        exchange = row.get("SEM_EXM_EXCH_ID")
        if exchange not in _EQ_SEGMENT:
            continue
        if row.get("SEM_SEGMENT") == "I" and row.get("SEM_INSTRUMENT_NAME") == "INDEX":
            dhan_sym = row.get("SEM_TRADING_SYMBOL", "")
            out.append(
                Instrument(
                    broker="dhan",
                    exchange=exchange,
                    segment="IDX",
                    symbol=_INDEX_SYMBOLS.get(dhan_sym, dhan_sym.replace(" ", "")),
                    broker_token=row["SEM_SMST_SECURITY_ID"],
                    name=row.get("SEM_CUSTOM_SYMBOL") or None,
                    lot_size=1,
                    tick_size=Decimal("0.05"),
                )
            )
            continue
        if row.get("SEM_SEGMENT") != "E":
            continue
        if row.get("SEM_INSTRUMENT_NAME") != "EQUITY" or row.get("SEM_SERIES") not in ("EQ", "BE"):
            continue
        try:
            tick = Decimal(row["SEM_TICK_SIZE"]) / 100
            lot = int(float(row.get("SEM_LOT_UNITS") or 1))
        except (ValueError, ArithmeticError, KeyError):
            continue
        out.append(
            Instrument(
                broker="dhan",
                exchange=exchange,
                segment="EQ",
                symbol=row["SEM_TRADING_SYMBOL"],
                broker_token=row["SEM_SMST_SECURITY_ID"],
                name=row.get("SEM_CUSTOM_SYMBOL") or None,
                lot_size=max(lot, 1),
                tick_size=tick if tick > 0 else Decimal("0.05"),
            )
        )
    return out


def _candles_frame(data: dict[str, Any] | None) -> pd.DataFrame:
    """Dhan chart response (parallel arrays, epoch-second timestamps) -> our candle frame."""
    cols = ["ts", "open", "high", "low", "close", "volume"]
    data = data or {}
    ts = data.get("timestamp") or []
    if not ts:
        return pd.DataFrame(columns=cols)
    n = len(ts)
    for key in ("open", "high", "low", "close", "volume"):
        if len(data.get(key) or []) != n:
            raise BrokerError("Dhan: malformed candle response (array lengths differ)")
    return pd.DataFrame(
        {
            # TODO(verify): epoch seconds assumed (docs say "Epoch timestamp"), bar open time.
            "ts": [datetime.fromtimestamp(int(t), UTC) for t in ts],
            "open": [_dec(v) for v in data["open"]],
            "high": [_dec(v) for v in data["high"]],
            "low": [_dec(v) for v in data["low"]],
            "close": [_dec(v) for v in data["close"]],
            "volume": [int(v) for v in data["volume"]],
        },
        columns=cols,
    )


def _chunks(start: datetime, end: datetime, max_days: int) -> list[tuple[datetime, datetime]]:
    out = []
    cur = start
    step = timedelta(days=max_days)
    while cur < end:
        nxt = min(cur + step, end)
        out.append((cur, nxt))
        cur = nxt
    return out


def _parse_token_validity(value: str | None) -> datetime | None:
    """Profile 'tokenValidity' like '30/03/2025 15:37' (IST) -> aware datetime."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y %H:%M").replace(tzinfo=IST)
    except ValueError:
        return None


async def _default_ws_connect(url: str) -> Any:
    import websockets

    # The URL holds the access token: never log it. websockets' own loggers go through our
    # masking (the token is registered as a secret in __init__).
    return await websockets.connect(url, max_size=2**20, ping_interval=None)


__all__ = [
    "DhanBroker",
    "parse_feed",
    "parse_scrip_master",
    "subscribe_messages",
]
