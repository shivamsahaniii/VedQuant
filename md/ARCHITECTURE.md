# Architecture

## Data flow

```
Broker data API ──► Data service ──► Scanner + strategy engine ──► Risk engine ──► Order manager ──► Broker trading API
 (WebSocket/REST)    (Redis, Timescale)    (signals)                 (approve/reject)   (place, track, reconcile)
                                                                         │                     │
                                                                         ▼                     ▼
                                                                    Alerts (Telegram)     Dashboard (Vue via FastAPI)
```

No order skips the risk engine.

## Multi-user

- Anyone can sign up. Each user connects their own broker accounts and keys, and has their own sections, strategies, risk limits, positions, P&L and kill switch.
- **User-owned data** carries `user_id` and is only visible to its owner. **Shared data:** `instruments`, `candles` and the built-in strategy templates.
- The scanner, order manager and reconciliation loop over users, and always use **that user's** broker account for that user's orders.
- Roles: `user` and `admin`. The admin can see platform health, disable a user, and use a platform-wide kill switch, but never sees any user's keys.
- Market data: each user's live data comes through their own data key. Whether one user's data feed may be shared with other users depends on the broker's terms: `TODO(verify)` before sharing.

## Components

### 1. Broker layer (`app/brokers/`)
One `BrokerAdapter` interface (see `md/BROKERS.md`) with an adapter per broker: `dhan.py` (first), later `upstox.py` and `delta.py`, and `paper.py` (simulated fills for paper trading). An adapter instance is created per user broker account with that account's decrypted keys. Trading and data capabilities are separate, so data can come from one broker and orders go through another.

### 2. Data service (`app/data/`)
- Subscribes to live ticks over WebSocket for the scanner universe.
- Builds candles (1m, 5m, 15m, 1d) from ticks; latest candles cached in Redis, history in TimescaleDB.
- Downloads historical candles for backtesting.
- Publishes "new candle" events (Redis pub/sub) to the scanner.

### 3. Scanner (`app/scanner/`)
- Universe: Nifty 500 or F&O list (configurable), filtered by price-within-capital and minimum volume.
- On each new candle, runs every active strategy for its symbols and emits `Signal` objects.
- Modes: `alerts_only` or `auto_trade`.

### 4. Strategy engine (`app/strategies/`)
- Code templates (Python classes) and builder strategies (JSON rules) share one interface: `generate_signals(candles) -> list[Signal]`.
- See `md/STRATEGIES.md`.

### 5. Risk engine (`app/risk/`)
- Pure, synchronous, fully unit-tested functions.
- Takes a `Signal` + account state, returns `Approved(order)` or `Rejected(reason)`.
- Handles position sizing, charges check, daily loss limit, exposure limits, kill switch (per user, plus the platform-wide one). See `md/RISK.md`.

### 6. Order manager (`app/orders/`)
- Places approved orders via the adapter, attaches stop loss / target.
- Tracks order status (via broker order updates or polling).
- Reconciles positions with the broker every N seconds and on startup.
- Auto square-off for intraday at the configured time.

### 7. Backtest (`app/backtest/`)
- Runs the same strategy code on historical candles with charges and slippage.
- Outputs: total return, win rate, max drawdown, trade count, trade list.

### 8. API + dashboard
- FastAPI exposes REST endpoints and a WebSocket for live P&L/positions.
- Vue dashboard: brokers, strategies, scanner, positions, P&L, logs, kill switch.

### 9. Alerts (`app/alerts/`)
Telegram (and email) for signals, orders, errors, loss-limit hits, token expiry.

## Processes (docker-compose services)

| Service | Runs |
| --- | --- |
| `api` | FastAPI app |
| `worker` | Celery worker: scanner loop, order manager, reconciliation |
| `beat` | Celery beat: scheduled jobs (token renewal, square-off, daily reports) |
| `feed` | Market data WebSocket consumer |
| `db` | PostgreSQL + TimescaleDB |
| `redis` | Redis |
| `web` | Vue frontend (nginx in production) |

## Trading sections

Intraday, Swing, Options and Crypto are separate "sections". Each has its own capital allocation, risk limits and P&L. A strategy belongs to exactly one section.
