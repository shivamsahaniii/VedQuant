"""Encryption of broker credentials, password hashing, and dashboard JWTs.

- Broker secrets are encrypted with Fernet (AES-128-CBC + HMAC) using ENCRYPTION_KEY,
  which lives only in the environment, never in the DB or repo.
- Every decrypted value is registered with the log masker, so it can never appear in logs.
- Passwords are hashed with Argon2.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import get_settings
from app.core.logging import register_secret


class DecryptionError(Exception):
    """Stored value could not be decrypted (wrong ENCRYPTION_KEY or corrupted data)."""


class InvalidTokenError(Exception):
    """JWT is missing, expired, malformed or signed with another secret."""


# ---------- credential encryption ----------


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.get_secret_value().encode())


def encrypt(plain: str, *, fernet: Fernet | None = None) -> bytes:
    if not isinstance(plain, str) or plain == "":
        raise ValueError("Only non-empty strings can be encrypted")
    return (fernet or _fernet()).encrypt(plain.encode("utf-8"))


def decrypt(token: bytes, *, fernet: Fernet | None = None) -> str:
    try:
        plain = (fernet or _fernet()).decrypt(bytes(token)).decode("utf-8")
    except InvalidToken:
        raise DecryptionError("Could not decrypt credential") from None
    register_secret(plain)
    return plain


def last4(value: str) -> str:
    """The only part of a secret the API/UI may ever show."""
    return value[-4:] if len(value) > 4 else ""


# ---------- passwords ----------

_password_hash = PasswordHash((Argon2Hasher(),))
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except Exception:  # noqa: BLE001 - malformed hash must not crash login
        return False


# ---------- JWT ----------

_ACCESS = "access"


def create_access_token(
    user_id: uuid.UUID | str, *, expires_minutes: int | None = None, now: datetime | None = None
) -> str:
    s = get_settings()
    issued = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": _ACCESS,
        "iat": issued,
        "exp": issued + timedelta(minutes=expires_minutes or s.jwt_expire_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id inside a valid access token, else raise InvalidTokenError."""
    s = get_settings()
    try:
        payload = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=[s.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "type"]},
        )
        if payload.get("type") != _ACCESS:
            raise InvalidTokenError("Wrong token type")
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError("Invalid or expired token") from exc
