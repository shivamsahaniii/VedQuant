# Phase 5: Expansion

**Goal:** swing trading, more templates, the no-code strategy builder, lifecycle gates, reports and mobile install.

Read first: `md/STRATEGIES.md` (builder format, lifecycle).

---

## Swing section

- [ ] **5.1 Swing section**
  - `swing` section settings; daily timeframe candles; overnight positions (no square-off); positions survive restarts via reconciliation.
  - **Check:** paper swing position held across two days with correct P&L.

- [ ] **5.2 Trailing stop loss**
  - Trailing SL (percent or ATR based) handled by the order manager, modifying the SL order.
  - **Check:** tests: SL only moves in the profit direction.

- [ ] **5.3 Swing templates**
  - `ema_cross`, `rsi_reversal`, `breakout_volume` with the same tests as Phase 2 (signals + no look-ahead).
  - **Check:** each can be backtested from the dashboard.

## No-code builder

- [ ] **5.4 Indicator registry**
  - `app/strategies/builder/indicators.py`: names → pandas-ta functions + param schemas; endpoint the dashboard uses for dropdowns.
  - **Check:** every registry entry computes on sample data.

- [ ] **5.5 Rules validation and compiler**
  - Pydantic models for the `rules` JSON (nested `all`/`any`, operators incl. `crosses_above`/`crosses_below`, SL, target, time window).
  - Compiler turns rules into a `Strategy` object. **No `eval`, no user code.**
  - **Check:** invalid rules rejected; a builder rule equal to a template gives the same signals as the template.

- [ ] **5.6 Builder UI**
  - Visual rule editor (add condition, AND/OR groups, indicator dropdowns), save, backtest.
  - **Check:** build the example strategy from `md/STRATEGIES.md` in the UI and backtest it.

## Lifecycle, reports, mobile

- [ ] **5.7 Lifecycle gates**
  - `draft → paper` needs a backtest on the current version; `paper → live` needs N paper trading days (default 10) and `TRADING_MODE=live`.
  - **Check:** API tests for each blocked and allowed move.

- [ ] **5.8 Reports**
  - Per section and per strategy: P&L by day/week/month, win rate, drawdown, charges paid.
  - **Check:** numbers match the `trades` table.

- [ ] **5.9 Email alerts**
  - Same events as Telegram, plus a daily summary email.
  - **Check:** daily summary received.

- [ ] **5.10 PWA**
  - Manifest, service worker, icons; installable on phone.
  - **Check:** installed on your phone and usable on a small screen.

---

## Phase done when

- [ ] Swing section paper-trades correctly with trailing SL.
- [ ] A builder strategy can be made, backtested and moved through the lifecycle from the dashboard.
- [ ] Reports and PWA work.
