from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

EVENT_LEVELS = ("debug", "info", "warning", "error", "critical")
EVENT_TYPES = ("signal", "order", "risk", "error", "auth", "broker", "system")


class EventLog(Base):
    """Append-only audit log. `user_id` is NULL for platform/system events. Never holds secrets."""

    __tablename__ = "event_log"
    __table_args__ = (
        CheckConstraint(f"level IN {EVENT_LEVELS}", name="level"),
        CheckConstraint(f"type IN {EVENT_TYPES}", name="type"),
        Index("ix_event_log_user_ts", "user_id", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ts: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(16), default="info")
    type: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
