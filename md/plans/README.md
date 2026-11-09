# Build plan: step by step

The roadmap (`md/ROADMAP.md`) is broken into small steps here, one file per phase. Each step is small enough to build, test and tick in one sitting.

**One-glance status:** [TRACKER.md](TRACKER.md)

## How to use

1. Open the current phase file. Do the steps **in order**; each one builds on the previous.
2. A step is finished only when its **Check** passes.
3. Tick the step here (`- [x]`) and the matching task in `md/ROADMAP.md`.
4. Commit with `phase-N: step N.M short description`.
5. Start the next phase only when the phase's **Phase done when** list is all true.

## Phases

| File | Phase | Steps | Result |
| --- | --- | --- | --- |
| [phase-1-foundation.md](phase-1-foundation.md) | 1. Foundation | 14 | Connect a broker from the dashboard, see live prices, 5m candles saved |
| [paper-trading-engine.md](paper-trading-engine.md) | **Current focus:** paper trading engine (agent team) | 4 + 9 agents | App reads the market, gives BUY/SELL/WAIT with reasons, paper-trades them (simulated data) |
| [phase-2-strategies-backtest.md](phase-2-strategies-backtest.md) | 2. Strategies and backtesting | 11 | Backtest 3 templates on 6+ months of data, charges included |
| [phase-3-scanner-risk-paper.md](phase-3-scanner-risk-paper.md) | 3. Scanner, risk engine, paper trading | 14 | One full week of unattended paper trading |
| [phase-4-small-live.md](phase-4-small-live.md) | 4. Small live (intraday) | 9 | Two weeks of live trading with tiny size, no mismatches |
| [phase-5-expansion.md](phase-5-expansion.md) | 5. Expansion | 10 | Swing section, no-code builder, reports, PWA |
| [phase-6-options-crypto.md](phase-6-options-crypto.md) | 6. Options and crypto | 11 | Options strategies, second broker, Delta Exchange crypto |

## Decisions made

- [x] **Multi-user web app.** Anyone can sign up and connect their own broker API keys from the dashboard.
- [x] **First broker: Dhan.** Upstox comes in Phase 6, Delta Exchange (crypto) in Phase 6.
- [x] **No real API keys while building.** Everything is built and tested with mocks and the `paper` adapter / demo feed. Real Dhan keys are only needed to confirm the adapter against the live API, and are added by a user from the dashboard.
- [x] **Web first**, PWA in Phase 5, native mobile app in Version 2.
- [x] **Paper trading only for now (2026-11-09).** Build the market-reading + signal + paper-trade loop on a market simulator ([paper-trading-engine.md](paper-trading-engine.md)). It pulls parts of Phases 2–3 forward. Users' own Dhan data/trading keys plug in later.
- [x] **Agent team (2026-11-09).** The engine is a team of rule-based agents (Market Watcher → Scanner → Entry → Exit → Odds → Risk+Sizer → Paper Broker → Alerts → Journal), modelled on the US *day-trader-skill* pack and adapted to NSE. Plain tested Python, not AI calls, so it is deterministic, free and auditable.

## Open questions (before Phase 4)

- [ ] SEBI rules for a platform that runs algos for other people (registration/empanelment through the broker?).
- [ ] Static IP: can many users' Dhan keys trade from one server IP?
- [ ] May one user's Dhan data feed be shared with other users?
