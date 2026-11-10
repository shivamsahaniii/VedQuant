# VedQuant tracker

**Updated:** 10 Nov 2026 (night) · **Current goal:** paper trading on **real** NSE prices (virtual money, no broker orders) from the first trading day after setup.

Detailed steps live in the phase files; this page is the one-glance status.

---

## 1. Where we are

| Area | Status | Notes |
| --- | --- | --- |
| Phase 1: Foundation | ✅ 19/19 | Sign-up/login, encrypted per-user broker keys (last 4 shown), Dhan adapter, live prices, candles, user isolation, no secrets in logs |
| Paper trading engine (agent team) | 🟡 22/32 | All 9 agents built and running; waiting on the first real-market session |
| Connections & Markets | 🟡 | Provider catalog, per-market data source, chart provider, Indices/Stocks/Crypto lists, candlestick charts |
| Real-price paper trading | 🟢 Dhan connected, Data plan active (to 9 Dec), 60 days of real 5m history loaded | Live ticks start on the first trading day (11 Nov); full replay of 9 Nov through all agents passed |
| Phase 2: Strategies & backtesting | 🟡 | Rules + **backtester** (`python -m app.backtest.run`); first report: [backtest-2026-11-10.md](backtest-2026-11-10.md), no strategy profitable yet |
| Phase 3: Scanner, risk, paper | 🟡 3/16 (+5 partly) | Scanner loop, paper order manager, dashboard done |
| Phase 4: Small live | ⬜ 0/10 | Blocked by 3 open questions (section 6) |
| Phase 5: Expansion | ⬜ 0/13 | Swing, no-code builder, reports, PWA |
| Phase 6: Options & crypto | ⬜ 0/13 | Crypto list exists; no exchange adapter |

**System:** 6 services running (db, redis, api, feed, engine, web) · 368 tests passing · lint clean · 5 database migrations · ~8,100 lines backend, ~3,900 lines frontend · URL `http://local.vedquant.com`.

---

## 2. What is built

### The agent team (runs on every closed candle, for every user's running strategies)
| # | Agent | What it does | Status |
| --- | --- | --- | --- |
| 1 | Market Watcher | Prices, 1m/5m candles, market mood (trend, strength, volatility, breadth, session) | ✅ |
| 2 | Scanner | ORB, VWAP cross, Supertrend, EMA cross, RSI reversal, volume breakout; closed candles only; each rule checks the market mood | ✅ |
| 3 | Entry Timer | Fresh data (≤90 s), 09:30–14:30 window, no chasing (>0.3 %), breakout not already failed, once per setup per day | ✅ |
| 4 | Exit Planner | Stop (range mid / ATR / % / level), target in R, NSE tick rounding, refuses stops too tight/wide and targets that can't pay charges 2× | ✅ |
| 5 | Odds ("time machine") | Thousands of seeded replays from the stock's own past sessions → honest verdict | ✅ (needs 15 past sessions; real history fixes this) |
| 6 | Risk + Sizer | 1 % risk/trade, position/cash caps, daily loss, trades/day, open positions, duplicates, kill switch, charges | ✅ (default limits) |
| 7 | Paper Broker | Market entry with slippage, SL-M + target (OCO), gap-through stops fill worse, net P&L after real charges, idempotent order refs | ✅ |
| 8 | Alerts & square-off | Stop/target checked every tick, 15:15 square-off | ✅ (in-app only, no Telegram yet) |
| 9 | Journal & dashboard | Live signals with reasons/odds/risk, positions, P&L, journal, per-strategy results, kill switch | 🟡 needs a full real session check |

### Screens
Overview (real P&L / open positions) · **Markets** (Indices/Stocks/Crypto + charts) · Algo Trading · Intraday · Swing · Paper Trading · Live Trading (locked) · Settings (Connections, accounts, keys).
Each section: add strategies (templates or **Build from scratch**: own rules from dropdowns), **Suggest only / Auto paper trade**, **Start / Pause**.

### Connections
| Ready | Coming soon (users can request) |
| --- | --- |
| VedQuant simulator, **Dhan**, VedQuant charts, TradingView widget (crypto only) | Angel One, Fyers, Zerodha, Upstox, ICICI Breeze, Binance, Delta Exchange India, CoinDCX, TradingView Advanced Charts |

### Real-price paper trading
- Feed picks the source every 30 s: your connected Dhan (if chosen for Stocks/Indices) or the simulator.
- Each morning: Dhan instrument list + 60 days of real 5m candles + today's 1m candles.
- Live 09:00–15:35 IST on trading days; holidays from the `nse_holidays` setting (10 and 24 Nov 2026 stored; verify with NSE).
- Never fakes prices: expired token or feed error → red banner on every page, no candles, no trades.
- Real and simulated candles never mix. Your real prices and trading are visible only to you.

---

## 3. What you need to do (before the first real session)

| # | Action | Where |
| --- | --- | --- |
| 1 | Confirm the NSE holiday for 10 Nov 2026 (most sources say closed; first session then **Wed 11 Nov**) | NSE holiday circular |
| 2 | Activate Dhan's **Data API** plan (about ₹499/month) | Dhan |
| 3 | Generate an **Access Token** + note your **Client ID** | web.dhan.co → My Profile → Access DhanHQ APIs |
| 4 | Add them yourself (never in chat) and click **Test** | VedQuant → Settings → Add broker → Dhan |
| 5 | Set **Indices data = Dhan** and **Stocks data = Dhan** | Settings → Connections |
| 6 | Tell me, the evening before the session, so I verify history/index/feed against your key | Chat |
| 7 | Every trading day: a fresh token (valid 24 h) | Settings → your Dhan card |
| 8 | Optional: which stocks to follow / trade | Markets tab, or tell me |

---

## 4. What is pending (ultimate product)

### Stage A: real-price paper trading, proven (now -> ~1 week)
| # | Task | Size |
|---|---|---|
| A1 | First live session 11 Nov: verify Dhan live packets, tick time, index feed (`TODO(verify)`) | 1 day |
| A2 | Limits page per section (capital, daily loss, trades/day, position %) + saved kill switch + daily halt | Small |
| A3 | Telegram alerts (signals, trades, errors, token expiry) + Dhan token auto-renew | Small |
| A4 | Backtest in the UI (Run backtest button, report page) | Small-medium |
| A7 | Change-password screen, accounts for invited people (sign-ups are closed), read-only viewer login | Small |
| A5 | UI leftovers: NIFTY card last close, remove 2 simulated signals, special sessions (Muhurat) | Small |
| A6 | One week of unattended paper trading (gate before live) | 5 market days |

### Stage B: a strategy that makes money (1-3 weeks, ongoing)
| # | Task |
|---|---|
| B1 | Improve strategies with the backtester: target R, trend-day filter, fewer trades (charges), per-stock selection |
| B2 | Longer history (6+ months) for backtests; walk-forward check so results are not over-fitted |
| B3 | Promote only strategies that are profitable in backtest AND in 10+ paper days |

### Hosting today (laptop, free)
- Built site + API in the `web` container (127.0.0.1:8080), public through Tailscale Funnel:
  https://vedquant.oarfish-alnitak.ts.net (on the laptop itself use http://local.vedquant.com or the same address with :8443).
- Sign-ups closed (`signups_open=false`). Set an account's password/email:
  `docker compose exec api python -m app.cli set-password <email> [--email <new>]`.
- Laptop must be on and awake 09:00-15:35 IST. Guide: deploy/share.md.

### Stage C: deployment to a server (later)
| # | Task |
|---|---|
| C1 | Server: AWS Lightsail Mumbai + static IP + domain (user) |
| C2 | Production setup: Caddy HTTPS, built frontend, prod compose, daily DB backups, server-only secrets, signups closed (me) |
| C3 | Dhan Redirect URL -> https://<domain>/dhan/callback; re-enter keys on the server |

### Stage D: real money, small (Phase 4)
| # | Task |
|---|---|
| D1 | Live order manager for Dhan: limit orders with price protection (no API market orders), 10 orders/s, fill tracking, OCO stop/target, square-off |
| D2 | Static IP registered on Dhan (from C1) |
| D3 | 2FA + password re-entry for key changes |
| D4 | Reconciliation: broker positions vs ours, alert + halt on mismatch |
| D5 | Answers: SEBI (algo for others), static IP for many users, data sharing |
| D6 | Unlock live: Rs 500-1,000, 2 weeks tiny size |

### Stage E: multi-client product
| # | Task |
|---|---|
| E1 | Per-user live data feeds (each client's own key) |
| E2 | Invite / onboarding, plans and billing, admin panel |
| E3 | Data export and delete (DPDP Act), privacy policy, terms, risk disclosures |
| E4 | Monitoring, uptime alerts, log retention, encryption-key backup |

### Stage F: expansion (Phase 5-6)
Swing trading (daily candles, trailing stop) · reports (monthly P&L, tax) · PWA phone app · more brokers (Angel One, Fyers, Zerodha, Upstox) · F&O options · crypto (24x7 rules) · news agent · 15m/1h live timeframes.

## 4b. Findings from the 9 Nov real-data replay
- Fixed: leftover cash made 1-share trades; position cap is now 33 % so 3 positions fit the capital.
- 4 of 5 trades were taken although the odds agent said "toward the stop"; all lost (net -1,154 for the day). Decide: use the odds as a gate? Measure with the backtester first.
- Dhan stock 5m history ends at 15:10 (indices 15:25); harmless (square-off 15:15).
- Special sessions (e.g. Sunday 8 Nov 14:20-15:10) are not traded: calendar is weekdays minus holidays.

## 5. Things to verify (`TODO(verify)` in code, 13 places)
- Dhan: history timestamp format/zone, index history (`INDEX`), live packet layout and tick time, several packets per message.
- Charges: Dhan intraday/delivery rates, DP charge.
- NSE tick-size bands (instrument tick sizes are preferred when known); holiday dates.
- Broker intraday leverage; TradingView widget options.

## 6. Open questions before real money (Phase 4)
1. SEBI rules for a platform that runs algos for other people (registration / broker empanelment?).
2. Can many users' Dhan keys place orders from one server IP (static IP rule)?
3. May one user's broker data be shown to other users (exchange data licensing)?

## 7. Housekeeping
- Git: branch `main`, 2 commits as shivamsahaniii <shivamsahaniii17@gmail.com>. **No remote yet** (needs your GitHub repo URL before pushing).
- Start locally: `docker compose up -d` (db, redis, api, feed, engine) + `cd frontend && npm run dev -- --host 127.0.0.1 --port 5173`; open http://local.vedquant.com.
- `md/README.md` and `md/CLAUDE.md` are read-only; unlock with `chmod u+w md/README.md md/CLAUDE.md` to update docs (they still say "Vedquant").
- Reference pack: `~/Downloads/skill-review/day-trader-skill` (MIT), read-only.
