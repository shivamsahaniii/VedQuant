from __future__ import annotations

from sqlalchemy import CheckConstraint, LargeBinary, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UpdatedAt, UUIDPk

ROLES = ("user", "admin")
TRADING_MODES = ("paper", "live")


class User(UUIDPk, CreatedAt, UpdatedAt, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES}", name="role"),
        CheckConstraint(f"trading_mode IN {TRADING_MODES}", name="trading_mode"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True)  # always stored lowercase
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    # Each user starts in paper mode; live also needs the platform TRADING_MODE=live.
    trading_mode: Mapped[str] = mapped_column(String(8), default="paper", server_default="paper")
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
