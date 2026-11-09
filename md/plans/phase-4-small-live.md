# Phase 4: Small live (intraday)

**Goal:** real money, tiny size (₹500–1000), with the app and broker always agreeing on orders and positions.

Read first: `md/BROKERS.md` (security, per-broker notes), `md/RISK.md` (kill switch, daily controls).

---

## Before writing live code

- [ ] **4.1 Rules and terms check**
  - Confirm current SEBI retail-algo requirements (static IP, algo registration/IDs, order rate limits) and Dhan's API terms. Write findings and dates in `md/BROKERS.md`.
  - **Because other people will use the app:** confirm whether a platform running algos for other users must be registered/empanelled with the exchange through the broker, whether many users' keys can trade from one server IP, and whether market data may be shared between users. Until this is clear, live trading stays limited to your own account (admin only).
  - **Check:** every requirement has a plan or is already done.

- [ ] **4.2 Production server**
  - Mumbai-region server with a static IP; whitelist it with the broker if required.
  - `docker-compose.prod.yml`, HTTPS reverse proxy (Caddy or nginx), daily DB backups, NTP time sync.
  - **Check:** dashboard reachable over HTTPS; backup restored once on a test DB.

## Live order path

- [ ] **4.3 Live trading methods in the adapter**
  - Implement `place_order`, `modify_order`, `cancel_order`, `order_status`, `positions`, `funds` from the broker's official docs. Unknowns → `TODO(verify)`.
  - Every live call checks `TRADING_MODE=live`; otherwise refuse.
  - **Check:** unit tests with recorded/mocked responses; live call in paper mode raises.

- [ ] **4.4 Idempotency and retries**
  - Send `order_ref` as the broker's client order tag (if supported). Retry with backoff only on safe errors; before retrying, look up the order by `order_ref` to avoid duplicates.
  - **Check:** test simulating timeout after the broker accepted → no second order.

- [ ] **4.5 Order updates**
  - Track status through the broker's order update stream or polling; update `orders`, `positions`, `trades`.
  - **Check:** partial fill, reject and cancel cases tested with mocks.

- [ ] **4.6 Reconciliation**
  - On startup and every N seconds compare app positions/orders with the broker. Any mismatch → Telegram alert + halt section.
  - **Check:** test that a fake mismatch halts trading and alerts.

- [ ] **4.7 Token renewal**
  - Scheduled job renews tokens before expiry (or alerts you to log in, for daily-OAuth brokers); old token overwritten.
  - **Check:** expiry within N hours → alert received.

## Go live, tiny

- [ ] **4.8 Live kill switch test**
  - With a 1-share order: place, then press the kill switch. Order cancelled / position closed at the broker.
  - **Check:** confirmed in the broker's own app.

- [ ] **4.9 Two weeks small live**
  - Intraday section capital ₹500–1000, strict limits, one strategy that passed backtest + paper. Daily review of app vs broker contract notes.
  - **Check:** 10 market days, no unexplained mismatch.

---

## Phase done when

- [ ] Two weeks of live intraday trading with tiny size and no unexplained mismatch between app and broker.
