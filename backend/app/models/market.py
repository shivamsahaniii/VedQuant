"""Shared market data (not user-owned): instruments and candles."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UpdatedAt, UUIDPk

TIMEFRAMES = ("1m", "5m", "15m", "1h", "1d")


class Instrument(UUIDPk, UpdatedAt, Base):
    """Symbol master per broker, refreshed daily."""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("broker", "exchange", "broker_token", name="uq_instruments_broker_token"),
        Index("ix_instruments_exchange_symbol", "exchange", "symbol"),
    )

    broker: Mapped[str] = mapped_column(String(32))
    exchange: Mapped[str] = mapped_column(String(16))  # NSE, BSE, NFO, ...
    segment: Mapped[str] = mapped_column(String(16))  # EQ, FUT, OPT, ...
    symbol: Mapped[str] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(128))
    broker_token: Mapped[str] = mapped_column(String(64))  # broker's security id
    lot_size: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    tick_size: Mapped[Decimal] = mapped_column(default=Decimal("0.05"))
    expiry: Mapped[date | None]
    strike: Mapped[Decimal | None]
    option_type: Mapped[str | None] = mapped_column(String(2))  # CE / PE


class Candle(Base):
    """OHLCV bar. TimescaleDB hypertable on `ts` (bar open time, UTC)."""

    __tablename__ = "candles"
    __table_args__ = (
        CheckConstraint(f"timeframe IN {TIMEFRAMES}", name="timeframe"),
        CheckConstraint("high >= low", name="high_gte_low"),
        CheckConstraint("volume >= 0", name="volume_non_negative"),
    )

    exchange: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    open: Mapped[Decimal]
    high: Mapped[Decimal]
    low: Mapped[Decimal]
    close: Mapped[Decimal]
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
