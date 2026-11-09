import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings

GOOD_KEY = Fernet.generate_key().decode()
GOOD_JWT = "x" * 48


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every test independent of the developer's real environment and .env file."""
    for var in ("TRADING_MODE", "ENCRYPTION_KEY", "JWT_SECRET", "MARKET_TZ", "APP_ENV"):
        monkeypatch.delenv(var, raising=False)


def make(**overrides: object) -> Settings:
    values: dict[str, object] = {"encryption_key": GOOD_KEY, "jwt_secret": GOOD_JWT}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_default_trading_mode_is_paper() -> None:
    s = make()
    assert s.trading_mode == "paper"
    assert s.is_live_allowed is False


def test_live_must_be_explicit() -> None:
    assert make(trading_mode="live").is_live_allowed is True


def test_invalid_trading_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        make(trading_mode="real")


def test_missing_encryption_key_fails() -> None:
    with pytest.raises(ValidationError, match="encryption_key"):
        Settings(_env_file=None, jwt_secret=GOOD_JWT)  # type: ignore[call-arg]


def test_missing_jwt_secret_fails() -> None:
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None, encryption_key=GOOD_KEY)  # type: ignore[call-arg]


def test_bad_encryption_key_fails() -> None:
    with pytest.raises(ValidationError, match="Fernet"):
        make(encryption_key="not-a-real-key")


def test_short_jwt_secret_fails() -> None:
    with pytest.raises(ValidationError):
        make(jwt_secret="short")


def test_secrets_hidden_in_repr() -> None:
    s = make()
    assert GOOD_KEY not in repr(s)
    assert GOOD_JWT not in repr(s)
    assert GOOD_KEY not in str(s.model_dump())


def test_market_timezone_default() -> None:
    assert str(make().tz) == "Asia/Kolkata"


def test_bad_timezone_fails() -> None:
    with pytest.raises(ValidationError):
        make(market_tz="Mars/Olympus")


def test_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENCRYPTION_KEY", GOOD_KEY)
    monkeypatch.setenv("JWT_SECRET", GOOD_JWT)
    monkeypatch.setenv("TRADING_MODE", "live")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.trading_mode == "live"
