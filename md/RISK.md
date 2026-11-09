# Risk engine, position sizing, charges

The risk engine (`app/risk/`) is pure code with no I/O: it receives a `Signal` and an `AccountState` snapshot and returns `Approved(OrderRequest)` or `Rejected(reason)`. It must have the most tests in the repo. All money is `Decimal`.

## Check order (stop at the first rejection)

1. **Kill switch** on (platform, user or section) → reject.
2. **Mode:** live order while platform `TRADING_MODE=paper` or the user's `trading_mode=paper` → route to paper adapter instead.
3. **Section enabled** and strategy status allows trading.
4. **Time window:** inside the strategy's entry window; intraday never after the no-new-entry time.
5. **Daily loss:** section's realised + unrealised loss ≥ `max_daily_loss` → reject and set `halted`.
6. **Trade count:** trades today ≥ `max_trades_per_day` → reject.
7. **Open positions:** ≥ `max_open_positions` → reject.
8. **Duplicate:** already holding this symbol for this strategy → reject.
9. **Stop loss present** → required on every signal.
10. **Position size** (below) ≥ 1 share / 1 lot → else reject "capital too small".
11. **Margin/funds:** required margin ≤ available funds for the section.
12. **Charges check** (below) passes.
13. **Exposure:** total section exposure stays within its limit.

Every rejection is written to `signals.reject_reason` and `event_log`.

## Position sizing

Per strategy, one of:

| Method | Quantity |
| --- | --- |
| `fixed_qty` | Set shares or lots, e.g. 2 lots |
| `fixed_amount` | floor(amount ÷ price), rounded down to lot size |
| `risk_percent` | floor((capital × risk%) ÷ (entry − stop loss)), rounded down to lot size |

Then cap by: available margin (using the broker's intraday leverage from config, not assumed), section exposure limit, and a max quantity per order. For F&O, quantity is always a multiple of the current lot size from `instruments`.

## Charges check

`app/risk/charges.py` estimates a round trip before entry:

- Brokerage (per broker, per order; from config)
- STT / CTT
- Exchange transaction charges
- SEBI fees
- Stamp duty
- GST on brokerage + exchange charges

Rates live in a config table/file with an `effective_from` date, because they change. **Verify current rates from the broker's charges page and NSE before going live.**

Rule: reject if `expected_gross_profit` (qty × |target − entry|) < `min_profit_multiple` × charges (default 2). This is what protects ₹500–1000 capital from trades that can't pay for themselves.

## Daily controls (scheduled)

- Intraday auto square-off at `square_off` time (default 15:15 IST), then cancel pending orders.
- Reset `risk_state` before market open.
- Loss limit hit → close section positions, halt section, Telegram alert.

## Kill switch

One API call / dashboard button per user: cancel all that user's open orders, close all their positions (market), set `kill_switch=true`. Resuming requires a manual action. The admin also has a platform-wide kill switch that does this for every user.

## Tests (minimum)

- Each rejection rule has a pass and a fail test.
- Sizing: each method, lot rounding, zero-quantity case, margin cap.
- Charges: known example trades match a hand calculation.
- Daily loss boundary (exactly at the limit).
- Paper/live routing never sends a live order in paper mode.
