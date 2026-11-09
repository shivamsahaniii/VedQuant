# Phase 6: Options and crypto

**Goal:** a second Indian broker, separate data/trading brokers per section, options strategies, and crypto on Delta Exchange.

Read first: `md/BROKERS.md`, `md/STRATEGIES.md` (options and crypto templates).

---

## Brokers

- [ ] **6.1 Upstox adapter**
  - Same process as Dhan: official docs first, mocked tests, `TODO(verify)` for unknowns. Upstox uses daily OAuth login, so add the "Log in with Upstox" button and callback.
  - **Check:** same checks as steps 1.10 and 4.3.

- [ ] **6.2 Data broker and trading broker per section**
  - Settings: global data broker, trading broker per section; symbol mapping between brokers via `instruments`.
  - **Check:** data from broker A, paper orders routed to broker B's section correctly.

## Options

- [ ] **6.3 Option chain and instruments**
  - Daily instrument refresh with expiry, strike, option type, lot size; option chain view (LTP, OI).
  - **Check:** chain for NIFTY current expiry matches the broker app.

- [ ] **6.4 Strike selection and expiry handling**
  - ATM / OTM-N selection, expiry choice (weekly/monthly), auto exit before expiry.
  - **Check:** tests for strike selection at different spot prices.

- [ ] **6.5 Multi-leg orders and combined P&L**
  - Place legs as one group, combined SL/target on group P&L, close all legs together; hedge leg first where margin needs it.
  - **Check:** tests: one leg fails → others handled safely.

- [ ] **6.6 Options risk and charges**
  - Lot-size sizing, options margin, options STT/charges in the charges calculator.
  - **Check:** hand-calculated options trade charges match.

- [ ] **6.7 Options templates**
  - `short_straddle`, `iron_condor`, `bull_call_spread`; options backtest using historical option data (if the broker provides it — verify).
  - **Check:** each runs in paper mode for a week.

## Crypto

- [ ] **6.8 Delta Exchange adapter**
  - Signed requests (verify the signing scheme from official docs), symbols, contract sizes, India-specific terms.
  - **Check:** `test_connection`, `historical`, `stream` work; signing unit-tested.

- [ ] **6.9 Crypto section and 24x7 scheduling**
  - `crypto` section; scheduler without market hours; daily risk reset at a chosen time; crypto charges.
  - **Check:** paper trading runs over a weekend.

- [ ] **6.10 Crypto templates**
  - `grid`, `trend_follow`.
  - **Check:** backtest + one week paper each.

- [ ] **6.11 Live rollout**
  - Same tiny-size approach as Phase 4 for options and crypto separately.
  - **Check:** two weeks each with no unexplained mismatch.

---

## Phase done when

- [ ] Options and crypto sections each trade with their own capital, limits and P&L.
- [ ] Data and trading brokers can be chosen separately per section.

---

Anything after this goes to **Version 2** (e.g. native mobile app on the same backend API).
