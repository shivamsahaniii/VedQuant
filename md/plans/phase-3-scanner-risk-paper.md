# Phase 3: Scanner, risk engine, paper trading

**Goal:** the full trading loop working end to end with the `paper` broker: scan → signal → risk check → order → SL/target → square-off → P&L → alerts.

**Multi-user:** sections, limits, signals, orders, positions, trades, risk state, kill switch and Telegram chat are all **per user**. The scanner and order manager loop over users and always act for one user at a time with that user's broker account. The admin has a platform-wide kill switch.

Read first: `md/RISK.md` (all of it), `md/ARCHITECTURE.md` (scanner, order manager).

---

## Risk engine (build and test this first)

- [ ] **3.1 Sections and risk state**
  - *Partly done: `signals` table and AccountState exist; `sections` and `risk_state` tables not yet (limits are defaults).*
  - Models + migrations: `sections` (capital, max_daily_loss, max_open_positions, max_trades_per_day, exposure limit, enabled), `risk_state` (per day per section), `signals`.
  - `AccountState` snapshot type: section settings, today's P&L, trade count, open positions, funds, kill switch.
  - **Check:** migration up/down; seed an `intraday` section.

- [ ] **3.2 Position sizing**
  - *Partly done: risk-percent sizing capped by position size, cash and max qty (app/risk/engine.py); no lot rounding / fixed methods yet.*
  - `app/risk/sizing.py`: `fixed_qty`, `fixed_amount`, `risk_percent`; round down to lot size; cap by margin (leverage from config), exposure limit and max qty per order.
  - **Check:** tests for each method, lot rounding, zero-quantity case, margin cap.

- [ ] **3.3 Risk engine checks**
  - *Mostly done: kill switch, halt, window, daily loss, trades, open positions, duplicate, stop, size, charges, with pass+block tests. Missing: section enabled, margin, exposure.*
  - `app/risk/engine.py`: pure function `evaluate(signal, state, config) -> Approved | Rejected` with all 13 checks **in the order** from `md/RISK.md`, stopping at the first rejection.
  - **Check:** a pass test and a fail test for every check; daily loss exactly at the limit; paper mode never produces a live order.

## Scanner

- [ ] **3.4 Universe and filters**
  - Load Nifty 500 or F&O list into `instruments`/settings; filters: price within section capital, minimum volume.
  - **Check:** test filter output on a sample list.

- [x] **3.5 Scanner loop (`alerts_only`)**
  - *Done in the engine worker (app/engine/pipeline.py): modes are 'suggest' (= alerts_only) and 'auto'.*
  - Listens to "new candle" events, runs every active strategy for its symbols, stores `signals`.
  - Mode setting: `alerts_only` / `auto_trade`.
  - **Check:** with the feed running, signals appear in the DB and the log.

## Orders

- [x] **3.6 Order manager (paper)**
  - *Done as app/orders/paper.py: entry + SL-M + LIMIT target (OCO), idempotent order_ref, tests in tests/test_paper_trading.py. Open trades act as positions.*
  - `app/orders/manager.py`: takes `Approved` orders, assigns `order_ref` UUID, places entry through the adapter (only path to `place_order`), then SL and target legs (`parent_order_id`). When one exits, cancel the other.
  - Models + migrations: `orders`, `positions`, `trades`.
  - **Check:** tests: entry → SL hit → trade closed with correct net P&L; entry → target hit; retry with same `order_ref` does not double-place.

- [ ] **3.7 Scheduled controls**
  - *Partly done: 15:15 square-off with tests; risk_state reset and loss-limit halt not yet.*
  - Square-off at 15:15 IST and cancel pending orders; reset `risk_state` before market open; loss limit hit → close section positions and halt.
  - **Check:** tests using a fake clock for each job.

- [ ] **3.8 Kill switch**
  - *Partly done: POST /trading/kill-switch closes all and pauses strategies; persisted kill_switch flag not yet.*
  - One endpoint: cancel all open orders, close all positions at market, set `kill_switch=true`. Resume only by a manual action.
  - **Check:** test that after kill switch the risk engine rejects every signal.

## Alerts and dashboard

- [ ] **3.9 Telegram alerts**
  - `app/alerts/telegram.py`: signals, orders, rejections, errors, loss-limit hit, token expiry. Never includes secrets.
  - **Check:** test message formatting; a real test message reaches your chat.

- [ ] **3.10 Celery worker and beat**
  - Move scanner, order manager and scheduled jobs to Celery `worker` + `beat` services in `docker-compose.yml`.
  - **Check:** `docker compose up` runs everything; jobs fire on time.

- [ ] **3.11 Intraday section settings page**
  - Edit capital and limits, enable/disable, choose `alerts_only` / `auto_trade`.
  - **Check:** changes take effect on the next signal.

- [x] **3.12 Dashboard: trading view**
  - *Done: Paper Trading + Intraday pages (positions, P&L, signal log with reasons, kill switch). P&L refreshes every 5 s; signals/trades push over WebSocket.*
  - Positions, today's P&L (live via WebSocket), signal log with reject reasons, big kill switch button.
  - **Check:** all four update live during a paper session.

- [ ] **3.13 Security: 2FA and password re-entry**
  - TOTP 2FA on login (`totp_secret_enc`), password re-entry required for broker add/edit/remove.
  - **Check:** API tests for both.

## Paper run

- [ ] **3.14 One-week paper run**
  - Run unattended for 5 market days. Each evening compare app P&L with a manual check of the trades.
  - **Check:** correct P&L every day, square-off every day, alerts received, no crashes.

---

## Phase done when

- [ ] The app paper-trades a full week of market days unattended with correct P&L, square-off and alerts.
- [ ] All risk tests pass.
