# VedQuant tracker

**Updated:** 9 Nov 2026 (evening) · **Current goal:** paper trading on **real** NSE prices (virtual money, no broker orders) from the first trading day after setup.

Detailed steps live in the phase files; this page is the one-glance status.

---

## 1. Where we are

| Area | Status | Notes |
| --- | --- | --- |
| Phase 1: Foundation | ✅ 19/19 | Sign-up/login, encrypted per-user broker keys (last 4 shown), Dhan adapter, live prices, candles, user isolation, no secrets in logs |
| Paper trading engine (agent team) | 🟡 22/32 | All 9 agents built and running; waiting on the first real-market session |
| Connections & Markets | 🟡 | Provider catalog, per-market data source, chart provider, Indices/Stocks/Crypto lists, candlestick charts |
| Real-price paper trading | 🟡 built, not yet run on a real key | Dhan live feed + history + indices + privacy + holidays; needs your key to verify |
| Phase 2: Strategies & backtesting | 🟡 4/13 | Rules done; **no backtester yet** |
| Phase 3: Scanner, risk, paper | 🟡 3/16 (+5 partly) | Scanner loop, paper order manager, dashboard done |
| Phase 4: Small live | ⬜ 0/10 | Blocked by 3 open questions (section 6) |
| Phase 5: Expansion | ⬜ 0/13 | Swing, no-code builder, reports, PWA |
| Phase 6: Options & crypto | ⬜ 0/13 | Crypto list exists; no exchange adapter |

**System:** 5 services running (db, redis, api, feed, engine) · 339 tests passing · lint clean · 5 database migrations · ~8,100 lines backend, ~3,900 lines frontend · URL `http://local.vedquant.com`.

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
Overview · **Markets** (Indices/Stocks/Crypto + charts) · Algo Trading · Intraday · Swing · Paper Trading · Live Trading (locked) · Settings (Connections, accounts, keys).
Each section: add strategies, **Suggest only / Auto paper trade**, **Start / Pause**.

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

## 4. What we build next (in order)

| # | Task | Why | Size |
| --- | --- | --- | --- |
| 1 | **Verify Dhan with your key** (history timestamps, index history, live packets) | 6 `TODO(verify)` items in `dhan.py` | Evening before session |
| 2 | **First real session, watched together** (09:15–15:30) | Proves the whole chain on real prices (closes A.9) | 1 market day |
| 3 | **Section settings & limits page** + saved kill switch + daily halt | Each user sets capital, daily loss, trades/day (now defaults ₹1,00,000 / ₹3,000 / 5) | Small |
| 4 | **Backtester** (same agents over months of real history, charges included) | Shows which strategies actually make money before any real money | Medium, most important |
| 5 | **Telegram alerts** (signals, trades, errors, token expiry) | Know what happens without watching the screen | Small |
| 6 | **One full week of unattended real-price paper trading** (step 3.14) | Gate before live trading | 5 market days |
| 7 | **Easier daily login** for the data source (or a free broker: Angel One / Fyers adapter) | Daily token paste is friction | Medium |
| 8 | **Per-user live feeds** (each user's own key → their own feed) | Today one live feed (first eligible user) | Medium |
| 9 | 2FA + password re-entry for key changes | Security before real money | Small |
| 10 | Answer the 3 open questions, then Phase 4 (small live) | Legal and technical gate | — |

Later: swing section with daily candles and trailing stops, no-code strategy builder, reports, PWA, options, crypto (24×7 rules), news agent.

---

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
- **Not under git yet**: nothing is versioned. Recommend `git init` + first commit.
- `md/README.md` and `md/CLAUDE.md` are read-only; unlock with `chmod u+w md/README.md md/CLAUDE.md` to update docs (they still say "Vedquant").
- Reference pack: `~/Downloads/skill-review/day-trader-skill` (MIT), read-only.
