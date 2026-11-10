from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import MIN_PASSWORD_LENGTH


class _Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return v.strip().lower()


class SignupIn(_Credentials):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


class LoginIn(_Credentials):
    pass


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - not a secret
    expires_in: int  # seconds


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None = None
    phone: str | None = None
    role: str
    trading_mode: str
    is_active: bool
    created_at: datetime


_PHONE = re.compile(r"^\+?[0-9]{7,15}$")


class ProfileUpdate(BaseModel):
    """Only the fields that are sent are changed. A new email needs the current password."""

    full_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    current_password: str | None = Field(default=None, max_length=128)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return " ".join(v.split()) or None if v is not None else None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        digits = re.sub(r"[\s\-()]", "", v)
        if not _PHONE.match(digits):
            raise ValueError("Enter a valid phone number (7-15 digits, optional +)")
        return digits

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return v.strip().lower() if v else v


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
