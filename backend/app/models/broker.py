from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UpdatedAt, UserOwned, UUIDPk

BROKER_STATUSES = ("new", "connected", "expired", "error", "disconnected")
CREDENTIAL_PURPOSES = ("trading", "data")


class BrokerAccount(UUIDPk, UserOwned, CreatedAt, UpdatedAt, Base):
    """One broker connection belonging to one user."""

    __tablename__ = "broker_accounts"
    __table_args__ = (
        CheckConstraint(f"status IN {BROKER_STATUSES}", name="status"),
        UniqueConstraint("user_id", "label", name="uq_broker_accounts_user_label"),
    )

    broker: Mapped[str] = mapped_column(String(32))  # registry key: "dhan", "paper", ...
    label: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
    last_checked_at: Mapped[datetime | None]
    token_expires_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)  # never contains secrets

    credentials: Mapped[list[BrokerCredential]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class BrokerCredential(UUIDPk, UserOwned, UpdatedAt, Base):
    """One encrypted secret field, split by purpose so trading and data keys are independent."""

    __tablename__ = "broker_credentials"
    __table_args__ = (
        CheckConstraint(f"purpose IN {CREDENTIAL_PURPOSES}", name="purpose"),
        UniqueConstraint(
            "broker_account_id", "purpose", "field", name="uq_broker_credentials_field"
        ),
    )

    broker_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(16))
    field: Mapped[str] = mapped_column(String(64))  # "client_id", "access_token", ...
    value_enc: Mapped[bytes] = mapped_column(LargeBinary)  # Fernet ciphertext, never plain
    last4: Mapped[str] = mapped_column(String(4))

    account: Mapped[BrokerAccount] = relationship(back_populates="credentials")
