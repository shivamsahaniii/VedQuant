"""Application settings loaded from environment variables (and `.env` in development).

Broker API keys are NOT settings: each user adds their own from the dashboard and they are
stored encrypted in the database.
"""

import base64
import binascii
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "VedQuant"
    app_env: Literal["dev", "test", "prod"] = "dev"

    # Platform-wide switch. Live orders also need the user's own trading_mode=live.
    trading_mode: Literal["paper", "live"] = "paper"

    database_url: str = "postgresql+asyncpg://vedquant:vedquant@localhost:5432/vedquant"
    redis_url: str = "redis://localhost:6380/0"

    # Required: the app refuses to start without them.
    encryption_key: SecretStr
    jwt_secret: SecretStr = Field(min_length=32)

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=60 * 12, gt=0)

    market_tz: str = "Asia/Kolkata"

    # Tests: open a fresh DB connection per use (no pool shared across event loops).
    db_null_pool: bool = False

    # Market simulator seed for the demo feed (same seed + same date = same prices).
    feed_seed: int | None = None

    telegram_bot_token: SecretStr | None = None

    @field_validator("encryption_key")
    @classmethod
    def _valid_fernet_key(cls, v: SecretStr) -> SecretStr:
        try:
            raw = base64.urlsafe_b64decode(v.get_secret_value().encode())
        except (binascii.Error, ValueError) as exc:
            raise ValueError("ENCRYPTION_KEY must be a Fernet key (url-safe base64)") from exc
        if len(raw) != 32:
            raise ValueError("ENCRYPTION_KEY must be a Fernet key (32 bytes, url-safe base64)")
        return v

    @field_validator("market_tz")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown time zone: {v}") from exc
        return v

    @field_validator("telegram_bot_token", mode="before")
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return None if v == "" else v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.market_tz)

    @property
    def is_live_allowed(self) -> bool:
        return self.trading_mode == "live"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
