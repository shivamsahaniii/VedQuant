"""Signals, orders and trades (md/DATABASE.md). Paper today; the same tables carry live orders later
(`mode`), so the dashboard and the journal never change when a user goes live.

An open trade is a position (one row per round trip); there is no separate positions table yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UpdatedAt, UserOwned, UUIDPk

SIDES = ("buy", "sell")
SIGNAL_STATUSES = ("suggested", "taken", "skipped", "refused", "blocked")
ORDER_ROLES = ("entry", "stop", "target", "exit")
ORDER_STATUSES = ("open", "filled", "cancelled", "rejected")
TRADE_STATUSES = ("open", "closed")
EXIT_REASONS = ("target", "stop", "square_off", "manual", "kill_switch")
MODES = ("paper", "live")


class Signal(UUIDPk, UserOwned, CreatedAt, Base):
    """Every setup the agents looked at, with what happened to it and why."""

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(f"side IN {SIDES}", name="side"),
        CheckConstraint(f"status IN {SIGNAL_STATUSES}", name="status"),
        UniqueConstraint("strategy_id", "trigger_key", name="uq_signals_strategy_trigger"),
        Index("ix_signals_user_created", "user_id", "created_at"),
    )

    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    section: Mapped[str] = mapped_column(String(16))
    exchange: Mapped[str] = mapped_column(String(8))
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(4))
    rule: Mapped[str] = mapped_column(String(32))
    trigger_key: Mapped[str] = mapped_column(String(96))
    bar_ts: Mapped[datetime]
    price: Mapped[Decimal]
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12))
    status_reason: Mapped[str] = mapped_column(Text, default="")
    mood: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    odds: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    risk: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Trade(UUIDPk, UserOwned, CreatedAt, UpdatedAt, Base):
    """One round trip. status=open is a live position; closed rows are the journal."""

    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint(f"side IN {SIDES}", name="side"),
        CheckConstraint(f"status IN {TRADE_STATUSES}", name="status"),
        CheckConstraint(f"mode IN {MODES}", name="mode"),
        CheckConstraint(
            f"exit_reason IS NULL OR exit_reason IN {EXIT_REASONS}", name="exit_reason"
        ),
        CheckConstraint("qty > 0", name="qty"),
        Index("ix_trades_user_status", "user_id", "status"),
    )

    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL")
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL")
    )
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    section: Mapped[str] = mapped_column(String(16))
    exchange: Mapped[str] = mapped_column(String(8))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[Decimal]
    entry_at: Mapped[datetime]
    stop: Mapped[Decimal]
    target: Mapped[Decimal]
    tick: Mapped[Decimal]  # the instrument's tick size, used for every fill of this trade
    max_loss: Mapped[Decimal]
    status: Mapped[str] = mapped_column(String(8), default="open")
    exit_price: Mapped[Decimal | None]
    exit_at: Mapped[datetime | None]
    exit_reason: Mapped[str | None] = mapped_column(String(16))
    gross_pnl: Mapped[Decimal | None]
    charges: Mapped[Decimal | None]
    net_pnl: Mapped[Decimal | None]


class Order(UUIDPk, UserOwned, CreatedAt, UpdatedAt, Base):
    """Broker orders. Stop and target legs of a trade cancel each other (OCO)."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(f"side IN {SIDES}", name="side"),
        CheckConstraint(f"role IN {ORDER_ROLES}", name="role"),
        CheckConstraint(f"status IN {ORDER_STATUSES}", name="status"),
        CheckConstraint(f"mode IN {MODES}", name="mode"),
        CheckConstraint("qty > 0", name="qty"),
    )

    order_ref: Mapped[str] = mapped_column(String(128), unique=True)  # idempotency key
    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    role: Mapped[str] = mapped_column(String(8))
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[int] = mapped_column(Integer)
    order_type: Mapped[str] = mapped_column(String(8))  # MARKET | LIMIT | SL-M
    price: Mapped[Decimal | None]
    trigger_price: Mapped[Decimal | None]
    status: Mapped[str] = mapped_column(String(10), default="open")
    avg_price: Mapped[Decimal | None]
    filled_at: Mapped[datetime | None]
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
