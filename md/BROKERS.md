# Brokers

## Goals

- Any user adds **their own** broker accounts from the dashboard, **no code or config edits**. A user's keys are only ever used for that user.
- The app is built and tested without real keys (mocks + `paper` adapter); keys are added by users when they are ready.
- **Trading API** and **data API** keys are separate and can each be added later.
- Data can come from one broker and orders go through another.
- Keys and tokens are always encrypted and never shown or logged in full.

## Adapter interface (`app/brokers/base.py`)

```python
class BrokerAdapter(Protocol):
    key: str                                  # "dhan", "upstox", "delta", "paper"
    display_name: str
    supports: set[str]                        # {"trading", "data", "historical", "options"}
    credential_fields: dict[str, list[FieldSpec]]  # {"trading": [...], "data": [...]}
    auth_type: Literal["api_key", "oauth"]

    # auth
    async def login_url(self, creds) -> str | None        # OAuth only
    async def complete_login(self, creds, callback_params) -> TokenSet
    async def test_connection(self, creds) -> ConnectionReport  # balance, permissions

    # trading
    async def place_order(self, req: OrderRequest) -> OrderAck
    async def modify_order(self, broker_order_id: str, changes: OrderChanges) -> OrderAck
    async def cancel_order(self, broker_order_id: str) -> None
    async def order_status(self, broker_order_id: str) -> OrderStatus
    async def positions(self) -> list[BrokerPosition]
    async def funds(self) -> Funds

    # data
    async def instruments(self) -> list[Instrument]
    async def historical(self, symbol, timeframe, start, end) -> pd.DataFrame
    async def stream(self, symbols) -> AsyncIterator[Tick]
```

`FieldSpec` = `name`, `label`, `secret: bool`, `help` (where to find it). The dashboard builds the "Add broker" form from these specs, so a new broker only needs a new adapter file plus registration in `app/brokers/registry.py`.

Rules:
- Implement only what the broker's **official** docs/SDK describe. Unknown endpoint/field → `TODO(verify)`.
- Adapters translate to/from the app's own types (`OrderRequest`, `Tick`, …); nothing outside `brokers/` sees broker-specific JSON.
- Respect each broker's rate limits with a per-adapter limiter.
- `paper.py` implements the same interface: fills at the next tick/candle price plus configurable slippage.

## No-code connection flow (dashboard: Settings → Brokers)

1. **Add broker** → pick from the registry list.
2. **Choose purpose:** trading, data, or both. Each purpose shows its own fields from `credential_fields`.
3. **Enter keys**, with the "where to find this" help text per field.
4. **Log in** (OAuth brokers): button opens the broker's login page; the callback endpoint stores the token.
5. **Test connection** before save: checks auth, funds, permissions.
6. **Status card** per broker: connected / expired / error, token expiry time, Reconnect, Edit keys, Disconnect.
7. **Select active brokers**: data broker (global) and trading broker per section.

Adding or changing a data key later must not require re-entering the trading key, and vice versa.

## Running without keys

| Available | App can do |
| --- | --- |
| No keys | Backtest on uploaded/cached data, demo dashboard |
| Data key only | Live scanning, alerts, paper trading |
| Data + trading keys | Everything, including live trading (if `TRADING_MODE=live`) |

## Credential security

- Encrypt every secret with the `ENCRYPTION_KEY` (Fernet/AES) before writing to `broker_credentials.value_enc`. The key lives in the environment or a secrets manager, never the database or repo.
- API returns only `last4` and `updated_at` for secrets; the full value never leaves the backend.
- A logging filter masks anything that looks like a credential; tests assert no secret appears in logs.
- Changing, viewing settings for, or removing a broker requires password re-entry; dashboard login supports 2FA (TOTP).
- Access tokens renewed by a scheduled job before expiry; old token overwritten immediately. Expiry within N hours → Telegram alert.
- **Disconnect** deletes all credential rows for that account.

## Per-broker notes (verify before building)

| Broker | Auth | To verify from official docs |
| --- | --- | --- |
| Dhan (first) | Access token / API key | Token validity, data API subscription, order rate limits, static IP rules, sandbox availability |
| Upstox | OAuth | Daily token flow, WebSocket limits, historical data range |
| Delta Exchange | API key + secret (signed requests) | Signing scheme, symbols, contract sizes, India-specific terms |

Also confirm current SEBI retail-algo requirements (static IP, algo registration/IDs, order rate limits) with each Indian broker before live trading.

Multi-user questions to verify before opening live trading to other users:
- Does an app that runs algos for other people need to be registered/empanelled (as an algo provider) with the exchange through the broker?
- Static IP: can many users' API keys be used from one server IP, or does each user need their own registered IP?
- May one user's market data feed be shared with other users?

## Dhan: facts from the official docs (read 2026-11-09, https://dhanhq.co/docs/v2/)

Adapter: `app/brokers/dhan.py`. Tests use mocked responses shaped like the docs' examples.

| Topic | What the docs say |
| --- | --- |
| REST base | `https://api.dhan.co/v2`, header `access-token: <JWT>` on every request |
| Credentials | Client ID + access token. Token generated at web.dhan.co (My Profile → Access DhanHQ APIs), **valid 24 hours**. API key + secret are valid 12 months and log in through a browser consent flow (`auth.dhan.co`). |
| Connection test | `GET /profile` (token validity, `dataPlan` Active/Deactive), `GET /fundlimit` (field is spelled `availabelBalance`) |
| Instruments | Public CSV `https://images.dhan.co/api-data/api-scrip-master.csv` (~28 MB). Security id column `SEM_SMST_SECURITY_ID`; tick size is in **paise** (checked against real rows). |
| History | Daily `POST /charts/historical` (toDate exclusive, back to listing). Intraday `POST /charts/intraday`, intervals 1/5/15/25/60, **max 90 days per request**, last 5 years. Parallel arrays + epoch timestamps. |
| Live feed | `wss://api-feed.dhan.co?version=2&token=…&clientId=…&authType=2`. Binary, little-endian. Max 5 connections × 5000 instruments, 100 per subscribe message. Needs the Data API plan. |
| Rate limits | Orders 10/s (250/min, 1000/h, 7000/day). Data 5/s (100,000/day). Quotes 1/s. Non-trading 20/s. |
| Errors | `{"errorType","errorCode","errorMessage"}`; `DH-901` bad/expired token, `DH-904` rate limit; feed codes 806–810 = auth/plan problems |
| Static IP | **Mandatory** for placing, modifying and cancelling orders. Each user sets a primary + secondary IP on their own Dhan account (`/ip/setIP`), locked for 7 days after setting. Reading orders/data needs no IP. |
| Sandbox | None documented |

Still `TODO(verify)` in the code (needs a real account to confirm): time zone of intraday `fromDate`/`toDate` (IST assumed), whether chart timestamps are bar open time, the time base of the feed's last-trade-time (receive time used for now), and whether one feed message can carry several packets.

Multi-user note: each user whitelists IPs on their own Dhan account, so every user would add our server's static IP. Whether Dhan allows the same IP on many accounts is `TODO(verify)` before Phase 4.
