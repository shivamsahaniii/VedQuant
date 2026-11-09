# Instructions for working in this repo

Read this file fully before making any change. It applies to AI coding assistants and human contributors alike.

## Project summary

Algo trading web app for NSE (Dhan, Upstox) and crypto (Delta Exchange). A Python backend scans the market, runs strategies, checks risk and places orders. A Vue dashboard controls everything. Full plan: `README.md` and `md/`.

## Current phase

Check `md/ROADMAP.md` for the current phase, then follow its step-by-step file in `md/plans/` in order. Do not build features from later phases early.

## Non-negotiable rules

1. **Risk engine first.** Every order goes `strategy → risk engine → order manager → broker adapter`. Never call a broker adapter's `place_order` from anywhere else.
2. **Paper mode is the default.** `TRADING_MODE=paper` unless the user explicitly sets `live`. Live order code must check this flag.
3. **Secrets.** Never hard-code API keys, tokens or passwords. Never print or log them (mask to last 4 chars). Credentials are stored encrypted (see `md/BROKERS.md`).
4. **No guessing broker APIs.** Before implementing an adapter method, read the broker's official API docs/SDK. If unsure of an endpoint or field, leave a `TODO(verify)` and say so; do not invent one.
5. **Money uses Decimal.** Prices, quantities, P&L and charges use `decimal.Decimal`, never float, in order and risk code. (pandas floats are fine for indicators.)
6. **Time zone.** All market logic uses `Asia/Kolkata`. Store timestamps in UTC (`timestamptz`), convert at the edges.
7. **Idempotent orders.** Every order gets a client-side `order_ref` (UUID) so retries never double-place.
8. **Tests with every change** to risk, sizing, charges or order code.

## Code layout

```
backend/
  app/
    api/            # FastAPI routers (thin: validate, call services)
    core/           # config, logging, security/encryption, db session
    brokers/        # base.py (interface) + one adapter per broker
    data/           # market data ingest, candle storage, websocket feeds
    strategies/     # base.py, templates/, builder/ (rule engine)
    scanner/        # universe, filters, scan loop
    risk/           # risk engine, position sizing, charges
    orders/         # order manager, reconciliation
    backtest/       # backtest runner, reports
    alerts/         # telegram, email
    models/         # SQLAlchemy models
    schemas/        # Pydantic schemas
  tests/
  alembic/
frontend/           # Vue 3 + Vite
md/                 # all project docs; md/plans/ = step-by-step phase plans
docker-compose.yml
```

## Conventions

- Python: type hints everywhere, `ruff` + `black`, `pytest`. Async FastAPI; SQLAlchemy 2.0 async.
- Migrations via Alembic only; never edit the DB by hand.
- Config via environment variables loaded in `app/core/config.py` (pydantic-settings).
- Logging: structured JSON logs; every order log line includes `order_ref`, `strategy_id`, `broker`.
- Frontend: Vue 3 Composition API, Pinia for state, a single API client module.
- Commit messages: `phase-N: short description`.

## When you finish a task

1. Run `pytest` and `ruff check`.
2. Update the relevant doc if behaviour changed.
3. Tick the task in `md/ROADMAP.md`.
4. Summarise what changed and anything left as `TODO(verify)`.
