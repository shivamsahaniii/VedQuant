from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UpdatedAt, UserOwned, UUIDPk

SECTIONS = ("intraday", "swing", "options", "crypto")
STRATEGY_STATUSES = ("draft", "paper", "live", "paused")
STRATEGY_KINDS = ("template", "builder")


class Strategy(UUIDPk, UserOwned, CreatedAt, UpdatedAt, Base):
    """A user's strategy. Lives in the user's library; `section` = the one section it trades in
    (NULL = not added to any section yet)."""

    __tablename__ = "strategies"
    __table_args__ = (
        CheckConstraint(f"section IS NULL OR section IN {SECTIONS}", name="section"),
        CheckConstraint(f"status IN {STRATEGY_STATUSES}", name="status"),
        CheckConstraint(f"kind IN {STRATEGY_KINDS}", name="kind"),
        UniqueConstraint("user_id", "name", name="uq_strategies_user_name"),
    )

    name: Mapped[str] = mapped_column(String(60))
    section: Mapped[str | None] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="template", server_default="template")
    template_key: Mapped[str | None] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL")
    )


class StrategyVersion(UUIDPk, UserOwned, CreatedAt, Base):
    """Snapshot of name/params/rules on every save."""

    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("strategy_id", "version", name="uq_strategy_versions_version"),
    )

    strategy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(60))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
