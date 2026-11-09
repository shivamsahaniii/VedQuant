# Phase 1: Foundation

**Goal:** the skeleton of a multi-user app: anyone can sign up, each user stores their own encrypted broker keys, the Dhan adapter is built from its official docs, and live prices (demo feed for now) with candles being saved.

**No real API keys are needed for this phase.** The Dhan adapter is tested with mocked responses; the dashboard and data pipeline run on the `paper` adapter's demo feed. When a user adds a real Dhan key, the same code works with live data.

Read first: `md/CLAUDE.md`, `md/ARCHITECTURE.md`, `md/SETUP.md`, `md/DATABASE.md`, `md/BROKERS.md`.

---

## Backend foundation

- [x] **1.1 Repo skeleton**
  - Create `backend/` with the folder layout from `md/CLAUDE.md` (empty `__init__.py` files), `frontend/`, `.gitignore`, `.env.example`.
  - `backend/requirements.txt` with the starting list from `md/SETUP.md`.
  - `ruff` + `black` + `pytest` config in `backend/pyproject.toml`.
  - **Check:** `ruff check` and `pytest` run (0 tests is fine).

- [x] **1.2 Docker Compose**
  - `docker-compose.yml` with `db` (`timescale/timescaledb` on Postgres 16), `redis`, `api`.
  - Named volume for DB data; healthchecks for `db` and `redis`.
  - **Check:** `docker compose up -d db redis` → both healthy.

- [x] **1.3 Config**
  - `app/core/config.py` using pydantic-settings; all variables from `md/SETUP.md`.
  - `TRADING_MODE` defaults to `paper`; app refuses to start if `ENCRYPTION_KEY` or `JWT_SECRET` is missing.
  - **Check:** test that default mode is `paper` and missing keys raise an error.

- [x] **1.4 Logging with secret masking**
  - `app/core/logging.py`: structlog JSON output.
  - A processor that masks secrets: known field names (`api_key`, `api_secret`, `access_token`, `password`, `token`, …) and long token-like strings → `****last4`.
  - **Check:** test logs a fake key in several ways and asserts the full value never appears.

- [x] **1.5 Encryption helpers**
  - `app/core/security.py`: `encrypt(str) -> bytes`, `decrypt(bytes) -> str`, `last4(str)` using Fernet with `ENCRYPTION_KEY`.
  - Password hashing (argon2 or bcrypt) and JWT create/verify.
  - **Check:** encryption round-trip test; wrong key fails; password hash verify test.

- [x] **1.6 DB session + Alembic**
  - `app/core/db.py`: SQLAlchemy 2.0 async engine and session dependency.
  - `alembic init`, async env, migration that enables the `timescaledb` extension.
  - **Check:** `alembic upgrade head` works on an empty DB.

- [x] **1.7 Phase 1 tables**
  - Models + migrations for `users` (with `role`, `is_active`, `trading_mode`), `broker_accounts`, `broker_credentials`, `platform_settings`, `user_settings`, `instruments`, `candles` (hypertable), `event_log` per `md/DATABASE.md`.
  - User-owned tables have `user_id` FK + index. `instruments` and `candles` are shared.
  - Money columns `numeric(18,4)`, times `timestamptz`.
  - **Check:** `alembic upgrade head` then `downgrade base` then `upgrade head` all succeed.

- [x] **1.8 Sign up, login, roles**
  - `POST /auth/signup` (open to anyone; can be closed via `platform_settings`), `POST /auth/login` → JWT, `GET /auth/me`.
  - First user created by a CLI command (`python -m app.cli create-admin`) gets `role=admin`; everyone else is `user`. New users start with `trading_mode=paper`.
  - `current_user` dependency used by every router; a helper that adds `WHERE user_id = current_user.id` to every user-owned query.
  - Login rate limiting (brute-force protection).
  - **Check:** API tests: signup, duplicate email blocked, login good/bad password, disabled user blocked, protected route without token → 401.

## Broker layer

- [x] **1.9 Broker interface, registry, paper adapter**
  - `app/brokers/base.py`: `BrokerAdapter` protocol, `FieldSpec`, and the app's own types (`OrderRequest`, `OrderAck`, `Tick`, `Instrument`, `Funds`, `ConnectionReport`, …) per `md/BROKERS.md`.
  - `app/brokers/registry.py`: list adapters and get one by key.
  - `app/brokers/paper.py`: implements the interface with simulated fills (next price + slippage), fake funds, and a fake tick stream for testing.
  - **Check:** unit tests for the paper adapter (place → filled, positions update, funds change).

- [x] **1.10 Dhan adapter (no real keys needed)**
  - Read Dhan's **official** API docs / DhanHQ SDK. Write down token validity, rate limits, WebSocket limits, historical data range, static IP rules and whether a sandbox exists in `md/BROKERS.md`.
  - Implement: `credential_fields` (with "where to find this" help text), `test_connection`, `instruments`, `historical`, `stream`. Trading methods stay `NotImplementedError` until Phase 4.
  - One adapter instance per user broker account, built from that account's decrypted keys. Per-account rate limiter. Anything unsure → `TODO(verify)`.
  - Tests use mocked HTTP/WebSocket responses shaped exactly like the official docs' examples.
  - **Check:** mocked tests pass for every method. Later, when a user adds real keys: `test_connection` returns funds, `historical` returns candles, `stream` gives ticks (keys never in output).

- [x] **1.11 Broker API endpoints (per user)**
  - `GET /brokers/available` (registry + `credential_fields`), `POST /brokers` (add account for the current user), `PUT /brokers/{id}/credentials/{purpose}` (add/replace `trading` or `data` keys separately), `POST /brokers/{id}/test`, `GET /brokers` (current user's accounts: status + `last4` only), `DELETE /brokers/{id}` (disconnect deletes all credential rows).
  - Every endpoint checks the account belongs to the current user (otherwise 404).
  - Every action written to `event_log` with `user_id` (no secrets).
  - **Check:** API tests: replacing the data key leaves the trading key untouched; responses never contain full secrets; disconnect removes credentials; user B gets 404 on user A's broker for every endpoint.

## Data

- [x] **1.12 Data service: ticks → candles**
  - `app/data/candle_builder.py`: pure function/class that turns ticks into 1m and 5m candles (IST market time, closes on boundary).
  - `feed` process: subscribe to a small symbol list, build candles, upsert into `candles`, cache latest candle per symbol in Redis, publish a "new candle" event.
  - Source of ticks: the `paper` adapter's **demo feed** (random-walk prices during market hours) when no data key exists; a user's Dhan data key when one is added.
  - Add `feed` service to `docker-compose.yml`.
  - **Check:** candle builder unit tests (boundaries, gaps, OHLCV correct); with the demo feed running, 5m candles appear in the DB.

## Frontend

- [x] **1.13 Vue app**
  - Vite + Vue 3 + vue-router + Pinia + one API client module (axios with JWT).
  - Pages: Sign up; Login; Settings → Brokers (add-broker form built from `credential_fields`, separate trading/data sections, test button, status card with Reconnect / Edit keys / Disconnect); Live Prices table for ~10 symbols (FastAPI WebSocket fed from Redis).
  - **Check:** two different users sign up in two browsers; each adds a broker and sees only their own; data key added later without touching the trading key; prices update live from the demo feed.

## Wrap up

- [x] **1.14 Phase 1 test pass and log audit**
  - *Done 2026-11-09: fake Dhan keys entered via the dashboard never appeared in logs or event_log; pytest + ruff green (327 tests).*
  - Tests present: encryption round-trip, secrets never logged, candle builder, broker credential separation, **user isolation** (user B can't read, edit, test or delete user A's broker or keys).
  - Enter fake keys through the dashboard, run the app, then `grep` all logs for each fake key.
  - **Check:** `pytest` and `ruff check` green; grep finds nothing.

---

## Phase done when

- [x] Any user can sign up and connect a broker entirely from the dashboard, and its data key can be added later without touching the trading key.
- [x] User A cannot see or use user B's brokers, keys or settings (tests).
- [x] Live prices for 10 symbols show on the dashboard (demo feed) and 5m candles are saved.
- [x] `grep` of logs shows no key or token.
- [x] Dhan adapter mocked tests pass (real-key check whenever a user adds keys).
