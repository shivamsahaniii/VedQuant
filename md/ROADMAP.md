# Roadmap

Work one phase at a time. Tick tasks as they're finished. Move on only when every "Done when" item is true.

**Current phase: 1**

---

## Phase 1: Foundation

- [x] Repo skeleton per `CLAUDE.md` layout; `docker-compose.yml` with `db` (Timescale), `redis`, `api`
- [x] `app/core`: config (pydantic-settings), JSON logging with secret masking, DB session, encryption helpers
- [x] Alembic setup; migrations for `users`, `broker_accounts`, `broker_credentials`, `platform_settings`, `user_settings`, `instruments`, `candles`, `event_log` (user-owned tables have `user_id`)
- [x] Sign up + login for any user (email + password, JWT), roles (`user`/`admin`), per-user data isolation; 2FA can come in Phase 3
- [x] `BrokerAdapter` interface + registry + `paper` adapter
- [x] Dhan adapter from the official docs: auth, test connection, instruments, historical candles, live stream (tested with mocks; real check when a user adds keys)
- [x] Broker API: add broker, add/replace trading key, add/replace data key, test connection, status, disconnect
- [x] Data service: stream ticks for a small symbol list (demo feed without keys, Dhan feed with a data key), build 1m/5m candles, store in TimescaleDB, cache latest in Redis
- [x] Vue app: sign up, login, Settings → Brokers page (form built from `credential_fields`), live price table for a few symbols
- [ ] Tests: encryption round-trip, secrets never logged, candle builder, user isolation

**Done when:**
- Any user can sign up and connect a broker entirely from the dashboard, and its data key can be added later without touching the trading key.
- User A cannot see or use user B's brokers, keys or settings (tests).
- Live prices for 10 symbols show on the dashboard (demo feed without keys) and 5m candles are saved.
- `grep` of logs shows no key or token.

---

## Phase 2: Strategies and backtesting

- [ ] `Strategy` interface, `Signal` type
- [ ] Templates: `orb`, `vwap_cross`, `supertrend`
- [ ] Historical data download job (per symbol, per timeframe)
- [ ] Charges calculator with configurable rates (`md/RISK.md`)
- [ ] Backtest runner (same `generate_signals`), slippage + charges, metrics: return, win rate, max drawdown, trade count
- [ ] `strategies`, `strategy_versions`, `backtests` tables
- [ ] Dashboard: strategy list, edit params (copy-on-edit), run backtest, results page with equity curve and trade list
- [ ] Tests: no look-ahead, charges hand-checked examples

**Done when:** each template can be backtested on 6+ months of data from the dashboard, with charges included.

---

## Phase 3: Scanner, risk engine, paper trading

- [ ] Universe (Nifty 500 / F&O list) + filters (price within capital, min volume)
- [ ] Scanner loop on new-candle events; `alerts_only` mode
- [ ] Risk engine with all checks in `md/RISK.md` + full tests
- [ ] Position sizing: `fixed_qty`, `fixed_amount`, `risk_percent`
- [ ] Order manager using the `paper` adapter: entry + SL + target, square-off, `orders`, `positions`, `trades`
- [ ] Sections table with capital and limits; intraday section settings page
- [ ] Telegram alerts: signals, orders, rejections, errors, token expiry
- [ ] Dashboard: positions, today's P&L, signal log, kill switch
- [ ] 2FA on login; password re-entry for broker changes

**Done when:** the app paper-trades a full week of market days unattended with correct P&L, square-off and alerts, and the risk tests pass.

---

## Phase 4: Small live (intraday)

- [ ] Confirm SEBI retail-algo requirements, rules for platforms offering algos to other users, and broker API terms; set up static IP if required
- [ ] Live order path in the real adapter (place, modify, cancel, status) behind `TRADING_MODE=live`
- [ ] Reconciliation with broker positions on startup and every N seconds; mismatch → alert + halt
- [ ] Idempotent `order_ref`, retry with backoff, no double orders
- [ ] Live kill switch tested against the real broker with a 1-share order
- [ ] Section capital ₹500–1000, strict limits

**Done when:** two weeks of live intraday trading with tiny size and no unexplained mismatch between app and broker.

---

## Phase 5: Expansion

- [ ] Swing section: daily timeframe, overnight positions, trailing stop loss
- [ ] Templates: `ema_cross`, `rsi_reversal`, `breakout_volume`
- [ ] No-code strategy builder (rules format in `md/STRATEGIES.md`) + builder UI
- [ ] Strategy lifecycle gates (backtest before paper, paper period before live)
- [ ] Reports per section and per strategy
- [ ] Email alerts; PWA install for mobile

---

## Phase 6: Options and crypto

- [ ] Upstox adapter
- [ ] Data broker and trading broker selectable separately per section
- [ ] Options: option chain, strike selection (ATM/OTM), multi-leg orders, expiry handling, combined P&L
- [ ] Options templates: `short_straddle`, `iron_condor`, `bull_call_spread`
- [ ] Delta Exchange adapter (signed requests), crypto section, 24x7 scheduling
- [ ] Crypto templates: `grid`, `trend_follow`

---

## Version 2 (later)

Anything not listed above, including a native mobile app on the same backend API.
