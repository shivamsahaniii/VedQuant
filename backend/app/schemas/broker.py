from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Purpose = Literal["trading", "data"]


class BrokerCreate(BaseModel):
    broker: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=64)

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Label is required")
        return v


class CredentialsIn(BaseModel):
    """Field name -> value. Fields not sent keep their saved value."""

    fields: dict[str, str] = Field(min_length=1, max_length=20)

    def __repr__(self) -> str:  # never print values
        return f"CredentialsIn(fields={sorted(self.fields)})"


class CredentialFieldOut(BaseModel):
    name: str
    label: str
    secret: bool
    required: bool
    saved: bool
    last4: str | None = None  # secret fields: only the last 4 characters
    value: str | None = None  # non-secret fields (e.g. client id) may be shown
    updated_at: datetime | None = None


class PurposeOut(BaseModel):
    fields: list[CredentialFieldOut]
    complete: bool  # every required field saved
    needs_credentials: bool  # this broker has fields for this purpose at all


class BrokerAccountOut(BaseModel):
    id: uuid.UUID
    broker: str
    broker_name: str
    is_paper: bool
    supports: list[str]
    label: str
    status: str
    last_checked_at: datetime | None
    token_expires_at: datetime | None
    last_error: str | None
    created_at: datetime
    credentials: dict[str, PurposeOut]


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    purpose_ok: dict[str, bool]
    funds_available: Decimal | None = None
    token_expires_at: datetime | None = None
    account: BrokerAccountOut
