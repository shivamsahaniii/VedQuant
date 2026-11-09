# Strategies

## Interface (`app/strategies/base.py`)

```python
@dataclass
class Signal:
    strategy_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    ts: datetime                # candle close time
    price: Decimal              # reference price
    stop_loss: Decimal
    target: Decimal | None
    reason: str                 # human-readable, shown in logs/alerts

class Strategy(Protocol):
    section: Literal["intraday", "swing", "options", "crypto"]
    timeframe: str              # "5m", "15m", "1d", ...
    warmup: int                 # candles needed before first signal
    def generate_signals(self, symbol: str, candles: pd.DataFrame) -> list[Signal]: ...
```

Rules:
- Strategies **only produce signals**. They never size positions, check risk or place orders.
- Use only closed candles (no look-ahead). The backtester and live scanner call the same `generate_signals`.
- Each strategy is built from `params` (jsonb) so the dashboard can edit it.

## Lifecycle

`draft → paper → live` (and `paused`). Rules:
- Every save creates a new row in `strategy_versions`.
- Moving to `paper` requires at least one backtest on the current version.
- Moving to `live` requires a paper period (default 10 trading days, configurable) and `TRADING_MODE=live`.
- Editing a template creates a copy (`parent_id` = template) owned by that user; built-in templates are shared and read-only. A user only sees their own strategies.

## Built-in templates

| Key | Section | Idea | Main params |
| --- | --- | --- | --- |
| `orb` | Intraday | Opening range breakout | range minutes, buffer %, SL %, target R |
| `vwap_cross` | Intraday | Price crosses VWAP with volume | volume multiple, SL %, target % |
| `supertrend` | Intraday / Swing | Supertrend flip | period, multiplier |
| `ema_cross` | Swing | Fast/slow EMA crossover | fast, slow, timeframe |
| `rsi_reversal` | Swing | RSI oversold/overbought reversal | period, low, high |
| `breakout_volume` | Swing | N-day high breakout with volume | lookback, volume multiple |
| `short_straddle` | Options | Sell ATM CE+PE | entry time, SL per leg, exit time (Phase 6) |
| `iron_condor` | Options | Short strangle + hedges | wing width (Phase 6) |
| `bull_call_spread` | Options | Buy ATM CE, sell OTM CE | strike gap (Phase 6) |
| `grid` | Crypto | Grid buy/sell levels | range, grids (Phase 6) |
| `trend_follow` | Crypto | EMA trend + trailing stop | periods (Phase 6) |

Phase 2 builds `orb`, `vwap_cross`, `supertrend` first.

## No-code builder format (`rules` jsonb)

```json
{
  "timeframe": "5m",
  "entry": {
    "side": "BUY",
    "all": [
      {"left": {"ind": "rsi", "period": 14}, "op": "<", "right": {"value": 30}},
      {"left": {"ind": "close"}, "op": ">", "right": {"ind": "ema", "period": 20}}
    ]
  },
  "exit": {
    "any": [
      {"left": {"ind": "rsi", "period": 14}, "op": ">", "right": {"value": 70}}
    ]
  },
  "stop_loss": {"type": "percent", "value": 1.0},
  "target": {"type": "percent", "value": 2.0},
  "time": {"entry_after": "09:20", "entry_before": "14:30", "square_off": "15:15"}
}
```

- Groups: `all` (AND) and `any` (OR), nestable.
- Operators: `<`, `<=`, `>`, `>=`, `crosses_above`, `crosses_below`.
- Indicator registry (`app/strategies/builder/indicators.py`) maps names to pandas-ta functions with param schemas; the dashboard dropdowns come from this registry.
- The builder compiles `rules` into a `Strategy` object; it never runs `eval` or user code.
- Validate rules with Pydantic before saving; invalid rules can't be saved.
