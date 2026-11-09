# Database

PostgreSQL 16 with the TimescaleDB extension. All timestamps are `timestamptz` (UTC). Money columns are `numeric(18,4)`. All changes via Alembic migrations.

**Multi-user rule:** every table below except `instruments`, `candles` and `platform_settings` has a `user_id` (FK `users`) and every query filters by it. Built-in strategy templates have `user_id = NULL` and are read-only.

## Tables

### `users`
One row per person using the app. `id`, `email`, `password_hash`, `role` (`user` / `admin`), `is_active`, `trading_mode` (`paper` default / `live`), `totp_secret_enc` (2FA), `created_at`.

### `broker_accounts`
One row per connected broker.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `user_id` | uuid FK | Owner; keys are only used for this user |
| `broker` | text | `dhan`, `upstox`, `delta`, `paper` |
| `label` | text | User's name for it, e.g. "Dhan main" |
| `status` | text | `connected`, `expired`, `error`, `disconnected` |
| `last_checked_at` | timestamptz | |
| `token_expires_at` | timestamptz | |
| `created_at` | timestamptz | |

### `broker_credentials`
Encrypted secrets, separated by purpose so trading and data keys can be added at different times.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `broker_account_id` | uuid FK | |
| `purpose` | text | `trading` or `data` |
| `field` | text | e.g. `api_key`, `api_secret`, `client_id`, `access_token` |
| `value_enc` | bytea | Encrypted value, never plain text |
| `last4` | text | Shown in the UI |
| `updated_at` | timestamptz | |

### `platform_settings`
Admin-only key/value: platform trading mode, platform kill switch, default limits, signups open/closed.

### `user_settings`
Per user key/value: active data broker, active trading broker per section, scanner universe.

### `sections`
`intraday`, `swing`, `options`, `crypto`: `capital`, `max_daily_loss`, `max_open_positions`, `max_trades_per_day`, `enabled`.

### `instruments`
Symbol master per broker: `symbol`, `exchange`, `segment`, `lot_size`, `tick_size`, `broker_token`, `expiry`, `strike`, `option_type`. Refreshed daily.

### `candles` (Timescale hypertable)
`exchange`, `symbol`, `timeframe`, `ts` (bar open time, UTC), `open`, `high`, `low`, `close`, `volume`. Primary key (`exchange`, `symbol`, `timeframe`, `ts`); 7-day chunks.

### `strategies`
| Column | Notes |
| --- | --- |
| `id`, `name`, `section` | |
| `kind` | `template` or `builder` |
| `template_key` | For templates, e.g. `orb`, `vwap_cross` |
| `params` | jsonb: periods, timeframe, SL, target, sizing |
| `rules` | jsonb: builder rules (see `md/STRATEGIES.md`) |
| `status` | `draft`, `paper`, `live`, `paused` |
| `version` | int |
| `parent_id` | Template it was copied from |

### `strategy_versions`
Snapshot of `params`/`rules` on every save.

### `signals`
`id`, `strategy_id`, `symbol`, `side`, `ts`, `price`, `reason`, `acted` (bool), `reject_reason`.

### `orders`
| Column | Notes |
| --- | --- |
| `id`, `order_ref` (uuid, unique) | Client ref for idempotency |
| `strategy_id`, `signal_id`, `broker_account_id`, `section` | |
| `mode` | `paper` / `live` |
| `symbol`, `side`, `qty`, `order_type`, `price`, `trigger_price` | |
| `broker_order_id`, `status`, `filled_qty`, `avg_price` | |
| `parent_order_id` | Stop loss / target legs point to entry |
| `created_at`, `updated_at` | |

### `positions`
Current open positions per section and broker, plus realised/unrealised P&L.

### `trades`
Closed round trips: entry, exit, qty, gross P&L, charges, net P&L.

### `backtests`
`strategy_id`, `params_snapshot`, `from`, `to`, `metrics` (jsonb), `trades` (jsonb), `created_at`.

### `event_log`
Append-only: `ts`, `user_id` (NULL for system events), `level`, `type` (`signal`, `order`, `risk`, `error`, `auth`, `broker`, `system`), `message`, `payload` jsonb. Payload is masked before saving; never contains secrets.

### `risk_state`
Per day per section: realised P&L, trade count, `halted` flag, `kill_switch` flag.
