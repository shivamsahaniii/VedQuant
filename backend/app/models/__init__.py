"""All models are imported here so Alembic autogenerate can find them."""

from app.models.base import Base
from app.models.broker import BrokerAccount, BrokerCredential
from app.models.event import EventLog
from app.models.market import Candle, Instrument
from app.models.settings import PlatformSetting, UserSetting
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Order, Signal, Trade
from app.models.user import User
from app.models.watchlist import WatchItem

__all__ = [
    "Base",
    "BrokerAccount",
    "BrokerCredential",
    "Candle",
    "EventLog",
    "Instrument",
    "Order",
    "PlatformSetting",
    "Signal",
    "Strategy",
    "StrategyVersion",
    "Trade",
    "User",
    "UserSetting",
    "WatchItem",
]
