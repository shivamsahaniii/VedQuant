# Phase 2: Strategies and backtesting

**Goal:** strategies that produce signals, and a backtester that tests them on real history with charges and slippage, all from the dashboard.

Read first: `md/STRATEGIES.md`, `md/RISK.md` (charges section).

---

## Strategy core

- [ ] **2.1 Strategy interface and Signal**
  - *Partly done: rules live in app/engine/setups.py (Rule registry + per-rule params), params validated by StrategyParams. No separate Strategy protocol yet.*
  - `app/strategies/base.py`: `Signal` dataclass and `Strategy` protocol per `md/STRATEGIES.md`. `price`, `stop_loss`, `target` are `Decimal`.
  - Template registry: key → class + param schema (Pydantic) so the dashboard can render param forms.
  - **Check:** unit test builds a dummy strategy from params and validates bad params are rejected.

- [ ] **2.2 Indicator helpers**
  - *Partly done: own EMA/ATR/ADX/VWAP/RSI/Supertrend in app/engine/indicators.py with no-look-ahead tests; not compared against pandas-ta.*
  - Thin wrappers over pandas-ta (EMA, VWAP, Supertrend, ATR, RSI) used by templates.
  - **Check:** values match pandas-ta on a fixed sample DataFrame.

- [x] **2.3 Template: `orb`**
  - *Done early in the paper engine (app/engine/setups.py, tests/test_setups.py). ORB uses the 09:15-09:30 range; stop/target in R are in the Exit Planner.*
  - Opening range (N minutes from 09:15 IST), breakout with buffer %, SL %, target in R.
  - One signal per symbol per day.
  - **Check:** tests on hand-made candles: breakout up, breakout down, no breakout, only one signal per day.

- [x] **2.4 Template: `vwap_cross`**
  - *Done early in the paper engine (app/engine/setups.py, tests/test_setups.py).*
  - Price crosses VWAP with volume ≥ multiple × average volume; VWAP resets daily.
  - **Check:** tests for cross up, cross down, cross without volume (no signal).

- [x] **2.5 Template: `supertrend`**
  - *Done early in the paper engine (app/engine/setups.py, tests/test_setups.py).*
  - Signal on Supertrend flip; SL at the Supertrend line.
  - **Check:** tests for flip up / flip down on hand-made data.

- [x] **2.6 No look-ahead test**
  - *Done early in the paper engine (app/engine/setups.py, tests/test_setups.py). Covers all 6 rules.*
  - Generic test for every template: signals from `candles[:n]` must equal the first signals from the full data up to candle n.
  - **Check:** passes for all three templates.

## Data and charges

- [ ] **2.7 Historical data download job**
  - Job (APScheduler for now) that downloads candles per symbol per timeframe through the data adapter, respects rate limits, skips ranges already stored, upserts into `candles`.
  - API endpoint to trigger it and see progress.
  - **Check:** 6 months of 5m data for 5 symbols stored with no duplicates or gaps on trading days.

- [ ] **2.8 Charges calculator**
  - *Partly done: app/risk/charges.py (Dhan intraday + delivery, effective_from), 2 hand-checked trades; needs a 3rd and verified rates.*
  - `app/risk/charges.py`: brokerage, STT/CTT, exchange charges, SEBI fees, stamp duty, GST.
  - Rates in a config file/table with `effective_from` and per broker/segment. **Get current rates from the broker charges page and NSE.**
  - **Check:** at least 3 hand-calculated example trades match to the paisa.

## Backtesting

- [ ] **2.9 Backtest runner**
  - `app/backtest/runner.py`: walks candles in order, calls the same `generate_signals`, simulates entry at next candle open + slippage, exits at SL / target / square-off time, subtracts charges.
  - Metrics: total return, win rate, max drawdown, trade count; trade list; equity curve.
  - **Check:** test on a tiny hand-made dataset where the expected trades and P&L are known.

- [ ] **2.10 Strategy tables and API**
  - **Done early (2026-11-09, on request):** `strategies` + `strategy_versions` tables (migration 0003), API `GET/POST /strategies`, `GET/PATCH/DELETE /strategies/{id}`, `GET /strategies/templates`, per-user isolation tests, and the dashboard flow: create from a template, add a strategy to a section (Intraday/Swing) from that section's tab, move/remove, delete drafts. Still to do here: `backtests` table, template param schemas per template, copy-on-edit of built-in templates.
  - Models + migrations: `strategies`, `strategy_versions`, `backtests`.
  - Endpoints: list templates, list/create/edit strategies (editing a built-in template creates a copy with `parent_id`; every save writes a `strategy_versions` row), run backtest, get results.
  - **Check:** API tests for copy-on-edit and versioning.

- [ ] **2.11 Dashboard: strategies and backtests**
  - Strategy list, edit params form (from the param schema), "Run backtest" with date range and symbols.
  - Results page: metrics cards, equity curve chart, trade list table.
  - **Check:** run each template from the browser on 6+ months of data and see results with charges included.

---

## Phase done when

- [ ] Each template (`orb`, `vwap_cross`, `supertrend`) can be backtested on 6+ months of data from the dashboard, with charges included.
- [ ] No look-ahead tests and charges hand-check tests pass.
