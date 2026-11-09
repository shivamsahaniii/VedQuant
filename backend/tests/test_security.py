import io
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.fernet import Fernet

from app.core import security
from app.core.config import get_settings
from app.core.logging import clear_registered, configure_logging, get_logger

SECRET = "dhan-access-token-1234567890-ABCDEFG"


# ---------- encryption ----------


def test_encrypt_round_trip() -> None:
    token = security.encrypt(SECRET)
    assert isinstance(token, bytes)
    assert SECRET.encode() not in token
    assert security.decrypt(token) == SECRET


def test_same_value_encrypts_differently_each_time() -> None:
    assert security.encrypt(SECRET) != security.encrypt(SECRET)


def test_wrong_key_cannot_decrypt() -> None:
    token = security.encrypt(SECRET)
    other = Fernet(Fernet.generate_key())
    with pytest.raises(security.DecryptionError):
        security.decrypt(token, fernet=other)


def test_tampered_data_cannot_decrypt() -> None:
    token = bytearray(security.encrypt(SECRET))
    token[-5] ^= 1
    with pytest.raises(security.DecryptionError):
        security.decrypt(bytes(token))


def test_decryption_error_does_not_contain_secret() -> None:
    other = Fernet(Fernet.generate_key())
    try:
        security.decrypt(security.encrypt(SECRET), fernet=other)
    except security.DecryptionError as exc:
        assert SECRET not in str(exc)
        assert exc.__cause__ is None


@pytest.mark.parametrize("bad", ["", None, 123])
def test_encrypt_rejects_empty_or_non_string(bad: object) -> None:
    with pytest.raises(ValueError):
        security.encrypt(bad)  # type: ignore[arg-type]


def test_decrypted_value_is_masked_in_logs() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    plain = security.decrypt(security.encrypt("innocent98765word"))
    get_logger().info(f"using {plain}", note=plain)
    assert "innocent98765word" not in stream.getvalue()
    clear_registered()


def test_last4() -> None:
    assert security.last4(SECRET) == "DEFG"
    assert security.last4("abcd") == ""


# ---------- passwords ----------


def test_password_hash_and_verify() -> None:
    h = security.hash_password("correct horse battery")
    assert h.startswith("$argon2")
    assert "correct horse battery" not in h
    assert security.verify_password("correct horse battery", h)
    assert not security.verify_password("wrong password!!", h)


def test_short_password_rejected() -> None:
    with pytest.raises(ValueError):
        security.hash_password("short")


def test_malformed_hash_returns_false() -> None:
    assert security.verify_password("anything12345", "not-a-hash") is False


# ---------- JWT ----------


def test_token_round_trip() -> None:
    uid = uuid.uuid4()
    assert security.decode_access_token(security.create_access_token(uid)) == uid


def test_expired_token_rejected() -> None:
    old = datetime.now(UTC) - timedelta(days=2)
    token = security.create_access_token(uuid.uuid4(), expires_minutes=5, now=old)
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


def test_token_signed_with_other_secret_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": 1, "exp": 9999999999},
        "some-other-secret-that-is-long-enough-123",
        algorithm="HS256",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(forged)


def test_alg_none_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": 1, "exp": 9999999999},
        key=None,
        algorithm="none",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(forged)


def test_wrong_token_type_rejected() -> None:
    s = get_settings()
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "iat": 1, "exp": 9999999999},
        s.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c"])
def test_garbage_token_rejected(garbage: str) -> None:
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(garbage)
