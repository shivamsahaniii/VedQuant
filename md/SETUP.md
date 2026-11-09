# Setup

## Prerequisites

- Docker + Docker Compose
- Python 3.12 (for running backend tools outside Docker)
- Node 20+ (for the frontend)
- A Telegram bot token (optional in Phase 1)

## First run

```bash
git clone <your-repo> vedquant && cd vedquant
cp .env.example .env          # then fill in values (see below)
docker compose up -d db redis
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Everything in Docker:

```bash
docker compose up --build
```

## Environment variables (`.env`)

| Variable | Example | Notes |
| --- | --- | --- |
| `APP_ENV` | `dev` | `dev` / `prod` |
| `TRADING_MODE` | `paper` | `paper` (default) or `live`. Live requires explicit change. |
| `DATABASE_URL` | `postgresql+asyncpg://vedquant:vedquant@localhost:5432/vedquant` | |
| `REDIS_URL` | `redis://localhost:6380/0` (host port 6380 so it never clashes with a local Redis) | |
| `ENCRYPTION_KEY` | *(generated)* | Fernet/AES key for broker credentials. Generate once, never commit. |
| `JWT_SECRET` | *(generated)* | Dashboard login sessions |
| `TELEGRAM_BOT_TOKEN` | | Optional |
| `TELEGRAM_CHAT_ID` | | Optional |
| `MARKET_TZ` | `Asia/Kolkata` | |

Broker API keys are **not** environment variables. They are added from the dashboard (Settings → Brokers) and stored encrypted in the database. See `md/BROKERS.md`.

Generate keys:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"                               # JWT_SECRET
```

## Backend dependencies (starting list)

```
fastapi
uvicorn[standard]
pydantic-settings
sqlalchemy[asyncio]
asyncpg
alembic
redis
celery
apscheduler
pandas
numpy
pandas-ta
vectorbt
cryptography
httpx
websockets
python-telegram-bot
structlog
pytest
pytest-asyncio
ruff
black
```

Add each broker's official Python SDK only when its adapter is built, after checking the SDK is current.

## Frontend dependencies (starting list)

`vue@3`, `vite`, `vue-router`, `pinia`, `axios`, a chart library (e.g. `lightweight-charts` for candles), a UI kit of your choice.

## Production

- Cloud server in the Mumbai region with a **static IP** (brokers may require whitelisting it; confirm with each broker).
- `docker compose -f docker-compose.prod.yml up -d`
- HTTPS via a reverse proxy (Caddy or nginx + Let's Encrypt).
- Daily database backups.
- Server time synced (NTP).
