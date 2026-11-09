# Algo Trading App

A web application that trades automatically on user-defined rules in the Indian stock market (NSE via Dhan / Upstox) and crypto (Delta Exchange). Version 1 focuses on intraday equity with small capital (₹500–1000), with swing, options and crypto added in later phases.

## How to use these docs

Read them in this order before writing code:

| File | What it covers |
| --- | --- |
| `CLAUDE.md` | Rules for any AI coding assistant (and humans) working in this repo |
| `md/ARCHITECTURE.md` | Components, data flow, folder structure |
| `md/SETUP.md` | Local development setup, Docker, environment variables |
| `md/DATABASE.md` | Tables and what each one stores |
| `md/BROKERS.md` | Broker adapter interface, no-code broker connection, key security |
| `md/STRATEGIES.md` | Strategy interface, templates, no-code builder format |
| `md/RISK.md` | Risk engine rules, position sizing, charges check |
| `md/ROADMAP.md` | Build phases with tasks and "done when" checks |
| `md/plans/` | Each phase broken into small numbered steps, one file per phase |

Start with **Phase 1** in `md/ROADMAP.md`. Do not start a phase until the previous one meets its "done when" list.

## Stack at a glance

- **Backend / trading engine:** Python 3.12, FastAPI, pandas, pandas-ta, vectorbt
- **Jobs:** Celery (or APScheduler for Phase 1)
- **Data:** PostgreSQL 16 + TimescaleDB, Redis
- **Frontend:** Vue 3 + Vite (web first, PWA later)
- **Alerts:** Telegram Bot API
- **Deploy:** Docker Compose on a Mumbai-region cloud server with a static IP

## Golden rules

1. No order reaches a broker without passing the risk engine.
2. No strategy goes live without a backtest and a paper-trading period.
3. API keys and tokens are always encrypted and never logged.
4. Every order, signal and error is logged with a timestamp.
5. Confirm current SEBI retail-algo rules and each broker's API terms before going live.

> This project is for personal use. Trading carries risk of loss; test thoroughly with paper trading first.
