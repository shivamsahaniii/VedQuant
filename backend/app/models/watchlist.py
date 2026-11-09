"""Each user's Markets lists: the indices, stocks and crypto they follow."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UserOwned, UUIDPk

ASSET_CLASSES = ("indices", "stocks", "crypto")


class WatchItem(UUIDPk, UserOwned, CreatedAt, Base):
    __tablename__ = "watch_items"
    __table_args__ = (
        CheckConstraint(f"asset_class IN {ASSET_CLASSES}", name="asset_class"),
        UniqueConstraint("user_id", "exchange", "symbol", name="uq_watch_items_user_symbol"),
    )

    asset_class: Mapped[str] = mapped_column(String(8))
    exchange: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(80), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
