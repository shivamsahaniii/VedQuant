"""Markets: the instruments users can follow, grouped as indices, stocks and crypto.

The catalog is a starting list; users can also add any symbol by hand. Whether an instrument has
live prices depends on the data source the user has connected (app/connectors/catalog.py); today
only the simulator's NIFTY 50 + 10 stocks have data.
`tv` is the TradingView symbol for the chart widget (None = not mapped, widget unavailable).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.connectors.catalog import AssetClass
from app.data.simulator import SIM_INDEX, SIM_STOCKS


@dataclass(frozen=True)
class MarketItem:
    asset_class: AssetClass
    exchange: str
    symbol: str
    name: str
    tv: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stock(sym: str, name: str) -> MarketItem:
    return MarketItem("stocks", "NSE", sym, name, f"NSE:{sym.replace('&', '_')}")


CATALOG: tuple[MarketItem, ...] = (
    MarketItem("indices", "NSE", "NIFTY50", "NIFTY 50", "NSE:NIFTY"),
    MarketItem("indices", "NSE", "BANKNIFTY", "NIFTY Bank", "NSE:BANKNIFTY"),
    MarketItem("indices", "NSE", "FINNIFTY", "NIFTY Financial Services", "NSE:CNXFINANCE"),
    MarketItem("indices", "NSE", "NIFTYIT", "NIFTY IT", "NSE:CNXIT"),
    MarketItem("indices", "NSE", "INDIAVIX", "India VIX", "NSE:INDIAVIX"),
    MarketItem("indices", "BSE", "SENSEX", "S&P BSE Sensex", "BSE:SENSEX"),
    *(_stock(s.symbol, s.name) for s in SIM_STOCKS),
    _stock("BHARTIARTL", "Bharti Airtel"),
    _stock("HINDUNILVR", "Hindustan Unilever"),
    _stock("BAJFINANCE", "Bajaj Finance"),
    _stock("MARUTI", "Maruti Suzuki"),
    _stock("SUNPHARMA", "Sun Pharmaceutical"),
    _stock("M&M", "Mahindra & Mahindra"),
    _stock("TITAN", "Titan Company"),
    _stock("HCLTECH", "HCL Technologies"),
    _stock("WIPRO", "Wipro"),
    _stock("NTPC", "NTPC"),
    MarketItem("crypto", "BINANCE", "BTCUSDT", "Bitcoin / Tether", "BINANCE:BTCUSDT"),
    MarketItem("crypto", "BINANCE", "ETHUSDT", "Ethereum / Tether", "BINANCE:ETHUSDT"),
    MarketItem("crypto", "BINANCE", "SOLUSDT", "Solana / Tether", "BINANCE:SOLUSDT"),
    MarketItem("crypto", "BINANCE", "BNBUSDT", "BNB / Tether", "BINANCE:BNBUSDT"),
    MarketItem("crypto", "BINANCE", "XRPUSDT", "XRP / Tether", "BINANCE:XRPUSDT"),
    MarketItem("crypto", "BINANCE", "DOGEUSDT", "Dogecoin / Tether", "BINANCE:DOGEUSDT"),
)
BY_KEY = {(m.exchange, m.symbol): m for m in CATALOG}

# Instruments the built-in simulator produces prices for.
SIMULATED = {(SIM_INDEX.exchange, SIM_INDEX.symbol), *((s.exchange, s.symbol) for s in SIM_STOCKS)}

# Followed by default the first time a user opens Markets.
DEFAULTS: tuple[tuple[str, str], ...] = (
    ("NSE", "NIFTY50"),
    ("NSE", "BANKNIFTY"),
    ("BSE", "SENSEX"),
    *((s.exchange, s.symbol) for s in SIM_STOCKS),
    ("BINANCE", "BTCUSDT"),
    ("BINANCE", "ETHUSDT"),
)

EXCHANGES: dict[AssetClass, tuple[str, ...]] = {
    "indices": ("NSE", "BSE"),
    "stocks": ("NSE", "BSE"),
    "crypto": ("BINANCE", "DELTA", "COINDCX"),
}
_SYMBOL = re.compile(r"^[A-Z0-9&\-_.]{1,30}$")


def valid_symbol(symbol: str) -> bool:
    return bool(_SYMBOL.match(symbol))


def tv_symbol(asset: AssetClass, exchange: str, symbol: str) -> str | None:
    known = BY_KEY.get((exchange, symbol))
    if known:
        return known.tv
    if asset == "stocks" and exchange in ("NSE", "BSE"):
        return f"{exchange}:{symbol.replace('&', '_')}"
    if asset == "crypto" and exchange == "BINANCE":
        return f"BINANCE:{symbol}"
    return None
