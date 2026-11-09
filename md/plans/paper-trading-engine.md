# Paper trading engine (market brain)

**Decided 2026-11-09:** build the full "read the market → decide → trade" loop for **paper trading only**, on **simulated market data**. Later each user connects their own Dhan account and the same loop runs on their real prices (data key), and eventually their real orders (trading key, Phase 4).

**Goal:** the app reads the current market, applies rules, and says **BUY / SELL / WAIT** with entry, stop loss, target, reason and confidence. In paper mode it can also take the trade with virtual money and track the result.

```
Market simulator (now) / Dhan feed (later)
      ↓ ticks every second
Candles 1m / 5m  ──►  Market context (trend, strength, volatility, breadth, time of day)
      ↓                         ↓
Strategy rules (ORB, VWAP, Supertrend, RSI …), filtered by today's market context
      ↓ signals with reason + confidence
Risk checks (stop loss, position size, limits)
      ↓
Paper order manager → paper broker (entry + SL + target, 3:15 square-off)
      ↓
Dashboard: market context, live signals, positions, P&L
```

Honest limits, shown in the app: rules give probabilities, not certainty. Simulated prices test that the machinery works; they say nothing about real profit.

---

## Steps

- [x] **E.1 Market simulator**
  - NIFTY 50 index + 10 stocks. Each stock = beta × index move + its own noise. Each session gets a regime (trend up, trend down, sideways, volatile), seeded by date so a day is repeatable. Intraday volume curve (busy open and close).
  - **Check:** tests show stocks move with the index, regimes produce the expected index drift, same date + seed = same prices.

- [x] **E.2 Feed service + candles** (= Phase 1 step 1.12)
  - Candle builder: ticks → 1m and 5m bars aligned to IST market time; volume from cumulative day volume.
  - `feed` process: simulator ticks → latest prices in Redis → closed candles upserted into `candles` → "new candle" event (Redis pub/sub).
  - **Check:** candle builder unit tests; with `feed` running, 1m/5m candles appear in the database.

- [x] **E.3 Live prices on the dashboard** (= Phase 1 step 1.13)
  - WebSocket from the API (fed by Redis) → live price table on Paper Trading with change %, high/low, mini trend.
  - **Check:** prices move live in the browser.

- [x] **E.4 Market context engine**
  - From index + stock candles: trend (EMA 20 + VWAP), strength (ADX), volatility (ATR vs normal), breadth (up vs down stocks), session phase (opening / mid-day / closing).
  - Output a "market mood" every candle, e.g. *Uptrend · strong · normal volatility · broad*.
  - **Check:** unit tests on hand-made candles; on simulator days the mood matches the regime most of the time.

- [ ] **E.5 → the agent team** (decided 2026-11-09, modelled on the US *day-trader-skill* pack, built for NSE)

  Vedquant runs a **team of agents inside the `engine` service**. Each agent has one job, reads what the
  previous one wrote, and hands on. They are plain, tested Python rules (not AI chat calls): same input →
  same answer, free to run every minute for every user, and every decision is logged with its reason.
  Reference: `~/Downloads/skill-review/day-trader-skill` (MIT), NSE ideas from `ankurgoels/trader-skills-india`.

  ```
  1 Market Watcher ─► 2 Scanner ─► 3 Entry Timer ─► 4 Exit Planner ─► 5 Odds (Time Machine)
        (done: E.1–E.4)                                                        │
  9 Journal ◄─ 8 Alerts & Square-off ◄─ 7 Paper Broker ◄─ 6 Risk Manager + Sizer ◄┘
  ```

  NSE rules used everywhere: session 09:15–15:30 IST, opening range 09:15–09:30, no entries before 09:30
  or after 14:30, flat by 15:15, NSE tick size, costs (brokerage + STT + exchange + GST + stamp ≈ 0.08–0.1 %
  round trip) counted in every target and P&L. Long and short allowed for intraday (paper), configurable.

  - [x] **A.1 Market Watcher** — prices, candles, market mood, breadth. *(Done in E.1–E.4.)*
  - [x] **A.2 Scanner agent** — on every closed candle, scans every symbol for setups: ORB, VWAP cross,
        Supertrend flip, RSI reversal, 20-day breakout, oversold bounce. Each rule says which market moods
        it trades in. Output: a watchlist ("matched a rule", never "a buy").
        **Check:** per-rule tests on hand-made candles + a no-look-ahead test.
  - [x] **A.3 Entry Timer** — confirms the trigger only on a CLOSED candle (a wick doesn't count), one
        trigger per setup per day, optional volume check, entry window. **Check:** waiting / triggered / expired tests.
  - [x] **A.4 Exit Planner** — stop (OR midpoint, OR low, ATR, %), target in R (1R/2R), rounded to NSE tick
        away from entry; refuses stops too tight for the spread and targets that don't cover costs.
        **Check:** rounding, refusal and cost tests.
  - [x] **A.5 Odds agent (Time Machine)** — for every signal: 2,000+ seeded replays of the rest of the day
        from the stock's own recent candles + the same rule on past days → "target first X %, stop first Y %",
        and an honest verdict (coin flip / leans to target / leans to stop). This is the signal's confidence.
        **Check:** same seed → same numbers; a hand-made pool with known odds.
  - [x] **A.6 Risk Manager + Sizer** — quantity = smallest of (max loss ÷ risk per share, position cap,
        cash). Checks: stop required, max loss/trade, daily loss limit, trades/day, reward:risk, entry window,
        duplicates, kill switch. Exits are never blocked. PASS/BLOCK with reasons.
        **Check:** a pass and a block test for each check.
  - [x] **A.7 Paper Broker / order manager** — signals table; per strategy **Suggest only** or **Auto paper
        trade**; entry + SL + target (one cancels the other); orders/positions/trades tables; idempotent `order_ref`.
        **Check:** entry → target and entry → stop give correct net P&L after costs.
  - [x] **A.8 Alerts & Square-off** — watches open positions every tick: stop, target, 15:15 square-off;
        pushes alerts to the browser.
  - [ ] **A.9 Journal & Dashboard** — live signals with reasons and odds, positions, today's P&L, closed
        trades, win rate per strategy and per setup; full unattended simulated session adds up.
        *Built 2026-11-09 (Paper Trading + Intraday pages, kill switch, manual close). Remaining check:
        watch one full real-hours session (09:15–15:30 IST) unattended and confirm the numbers add up.*
  - [ ] **Real-market follow-ups:** per-user section capital and limits (sections table); NSE holiday list
        (platform setting `nse_holidays`, TODO(verify)); back-fill 60 days of 5m history from the data broker
        so the Odds agent has past sessions; verify charge rates and tick sizes (TODO(verify) in code).
  - [ ] **Later agents:** News agent (NSE announcements, results dates, bulk/block deals, FII/DII) — needs
        real internet data, so after a data source is connected; skipped on simulated prices.

---

## Later (not now)

- Switch data source to a user's Dhan data key (adapter already built, Phase 1.10).
- Backtests on real historical data (Phase 2) to measure each rule's real win rate.
- Live orders through the user's Dhan trading key (Phase 4).

---

## Connections & Markets (added 2026-11-09)

- [x] **Connector catalog** (`app/connectors/catalog.py`, Settings → Connections): Indian brokers & data,
      crypto exchanges, charts. Available now: Vedquant simulator, Dhan, Vedquant charts (Lightweight
      Charts), TradingView widget (crypto only: NSE/BSE are not allowed in the free widget). Others are
      listed as *coming soon*; users can request them and requests are counted (`request_counts`).
- [x] **Per-user choices:** data source per market (indices / stocks / crypto) and chart provider; a
      broker source can only be chosen after that account is connected and tested.
- [x] **Markets tab:** Indices / Stocks / Crypto lists per user (`watch_items`), seeded with defaults,
      add from catalog or any symbol, live price + data status per row, candlestick chart with the
      user's signals as markers.
- [ ] **Per-user live feeds:** when a user picks Dhan (or another broker) as a data source, run a feed
      from *their* key for *their* symbols (never shared with other users), replacing the simulator for them.
- [ ] **Next adapters, by request count:** Angel One / Fyers (free data), then a crypto exchange
      (crypto also needs 24×7 session rules in the engine: no 09:15–15:30 window, no square-off).
- [ ] **History back-fill** from the chosen data source (60 days of 5m candles) for charts and Odds.

---

## Paper trading on REAL prices (decided 2026-11-09)

"Paper trading" = real live market prices, virtual money, no orders sent to the broker.
The simulator is only a fallback for testing when no real source is chosen.

- [x] Dhan adapter: indices (IDX_I, NIFTY 50 = id 13, checked in the scrip master), exchange day
      open/high/low and previous close in every tick; change % measured from the previous close.
- [x] Feed chooses its source every 30 s (`app/data/source.py`): the first user (admins first) who
      picked a connected real broker for Stocks/Indices owns the live feed; otherwise the simulator.
- [x] On start of each day: Dhan instrument list + 60 days of real 5m candles + today's 1m candles.
- [x] Live window 09:00–15:35 IST on trading days; holidays from platform setting `nse_holidays`.
- [x] Never fakes prices: token expired / feed error → red banner, no candles, no trades.
- [x] Real and simulated candles never mix (candles cleared when the mode switches).
- [x] Privacy: a real feed's prices, mood, candles and trading are only for its owner.
- [ ] **Verify with the user's real key** (TODO(verify) in dhan.py): history timestamps, index
      history (`instrument: INDEX`), live packet layout. Do it the evening before the first session.
- [ ] Confirm the NSE holiday dates (10 Nov 2026 Balipratipada listed by most sources).
- [ ] First real session: watch it end to end, then a full week (step 3.14).
