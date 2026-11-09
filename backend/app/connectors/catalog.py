"""Connector catalog: every data / trading / chart provider a user can choose, and what each covers.

`status="available"` means VedQuant has a working adapter (app/brokers/registry.py) or component.
`status="coming_soon"` providers are listed so users can see the plan and request them; nothing is
sent to them and no API is guessed (md/CLAUDE.md: no guessing broker APIs).
Pricing notes are as understood on 2026-11-09. TODO(verify): confirm each on the provider's site.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Category = Literal["broker", "crypto", "charts"]
Status = Literal["available", "coming_soon"]
AssetClass = Literal["indices", "stocks", "crypto"]
ASSET_CLASSES: tuple[AssetClass, ...] = ("indices", "stocks", "crypto")


@dataclass(frozen=True)
class Connector:
    key: str
    name: str
    category: Category
    status: Status
    summary: str
    provides: tuple[str, ...]  # "market data", "trading", "charts"
    assets: tuple[AssetClass, ...]  # which Markets lists it can feed
    markets: tuple[str, ...]  # human-readable coverage
    pricing: str
    docs_url: str = ""
    broker_key: str | None = None  # adapter key when status == available (data/trading)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


CONNECTORS: tuple[Connector, ...] = (
    # ---------------------------------------------------------------- Indian brokers & data
    Connector(
        "paper",
        "VedQuant simulator",
        "broker",
        "available",
        "Built-in simulated NSE market for testing strategies safely, any time of day.",
        ("market data", "trading"),
        ("indices", "stocks"),
        ("NIFTY 50 + 10 large-cap NSE stocks (simulated)",),
        "Free",
        broker_key="paper",
        notes=("Prices are simulated, not real quotes.",),
    ),
    Connector(
        "dhan",
        "Dhan",
        "broker",
        "available",
        "Your own Dhan account: real-time NSE/BSE data (Data API) and order placement.",
        ("market data", "trading"),
        ("indices", "stocks"),
        ("NSE & BSE equity", "Indices", "F&O", "MCX"),
        "Trading API free; Data API about ₹499/month",
        "https://dhanhq.co/docs/v2/",
        broker_key="dhan",
        notes=("Orders need a static IP registered with Dhan.",),
    ),
    Connector(
        "angelone",
        "Angel One SmartAPI",
        "broker",
        "coming_soon",
        "Angel One's SmartAPI: live NSE/BSE data and orders.",
        ("market data", "trading"),
        ("indices", "stocks"),
        ("NSE & BSE equity", "Indices", "F&O", "MCX"),
        "Free for Angel One clients",
        "https://smartapi.angelbroking.com/docs",
    ),
    Connector(
        "fyers",
        "Fyers API",
        "broker",
        "coming_soon",
        "Fyers API v3: live data websocket and orders.",
        ("market data", "trading"),
        ("indices", "stocks"),
        ("NSE & BSE equity", "Indices", "F&O", "MCX"),
        "Free for Fyers clients",
        "https://myapi.fyers.in/docsv3",
    ),
    Connector(
        "zerodha",
        "Zerodha Kite Connect",
        "broker",
        "coming_soon",
        "Kite Connect: live data (paid plan) and orders.",
        ("market data", "trading"),
        ("indices", "stocks"),
        ("NSE & BSE equity", "Indices", "F&O", "MCX"),
        "Paid subscription for data",
        "https://kite.trade/docs/connect/v3/",
    ),
    Connector(
        "upstox",
        "Upstox API",
        "broker",
        "coming_soon",
        "Upstox API v2: market data feed and orders.",
        ("market data", "trading"),
        ("indices", "stocks"),
        ("NSE & BSE equity", "Indices", "F&O", "MCX"),
        "Check Upstox's current pricing",
        "https://upstox.com/developer/api-documentation/",
    ),
    Connector(
        "icici_breeze",
        "ICICI Direct Breeze",
        "broker",
        "coming_soon",
        "Breeze API for ICICI Direct accounts.",
        ("market data", "trading"),
        ("indices", "stocks"),
        ("NSE & BSE equity", "Indices", "F&O"),
        "Free for ICICI Direct clients",
        "https://api.icicidirect.com/breezeapi/documents/index.html",
    ),
    # ---------------------------------------------------------------- crypto exchanges
    Connector(
        "binance",
        "Binance",
        "crypto",
        "coming_soon",
        "Spot and futures crypto prices and orders.",
        ("market data", "trading"),
        ("crypto",),
        ("Crypto spot (USDT pairs)", "Crypto futures"),
        "Public market data free; trading fees per Binance",
        "https://developers.binance.com/docs/",
        notes=("Check that the exchange is available and compliant where you live.",),
    ),
    Connector(
        "delta_india",
        "Delta Exchange India",
        "crypto",
        "coming_soon",
        "INR-settled crypto futures and options.",
        ("market data", "trading"),
        ("crypto",),
        ("Crypto futures & options (INR)",),
        "Trading fees per Delta",
        "https://docs.delta.exchange/",
    ),
    Connector(
        "coindcx",
        "CoinDCX",
        "crypto",
        "coming_soon",
        "Indian crypto exchange with INR and USDT markets.",
        ("market data", "trading"),
        ("crypto",),
        ("Crypto spot (INR & USDT)",),
        "Trading fees per CoinDCX",
        "https://docs.coindcx.com/",
    ),
    # ---------------------------------------------------------------- charts
    Connector(
        "vedquant_charts",
        "VedQuant charts",
        "charts",
        "available",
        "Candlestick charts drawn from your connected data source, with your signals on them.",
        ("charts",),
        ("indices", "stocks", "crypto"),
        ("Any symbol with data in VedQuant",),
        "Free (TradingView Lightweight Charts™, Apache-2.0)",
        "https://tradingview.github.io/lightweight-charts/",
    ),
    Connector(
        "tradingview_widget",
        "TradingView chart widget",
        "charts",
        "available",
        "TradingView's own interactive chart and drawing tools for crypto and global symbols.",
        ("charts",),
        ("crypto",),
        ("Crypto (e.g. Binance pairs)", "Global symbols"),
        "Free widget (TradingView's own data)",
        "https://www.tradingview.com/widget-docs/",
        notes=(
            "Data comes from TradingView, not from your connected broker.",
            "NSE/BSE symbols are not available in the free widget (exchange licensing).",
        ),
    ),
    Connector(
        "tradingview_advanced",
        "TradingView Advanced Charts",
        "charts",
        "coming_soon",
        "Full TradingView charting library fed by your own broker data.",
        ("charts",),
        ("indices", "stocks", "crypto"),
        ("Any symbol with data in VedQuant",),
        "Requires a licence from TradingView",
        "https://www.tradingview.com/advanced-charts/",
    ),
)

BY_KEY = {c.key: c for c in CONNECTORS}


def catalog() -> list[dict[str, Any]]:
    return [c.as_dict() for c in CONNECTORS]


def data_sources_for(asset: AssetClass) -> list[Connector]:
    return [c for c in CONNECTORS if asset in c.assets and "market data" in c.provides]


def chart_providers() -> list[Connector]:
    return [c for c in CONNECTORS if c.category == "charts"]
