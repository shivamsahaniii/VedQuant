import io
import json
import logging
import uuid

import pytest

from app.core.logging import (
    clear_registered,
    configure_logging,
    get_logger,
    is_secret_name,
    mask_value,
    register_secret,
)

# Fake values shaped like real broker credentials.
API_KEY = "dhanKEY9f8e7d6c5b4a3210zzQQ"
ACCESS_TOKEN = "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiIxMTAwMDAwMDAwIn0.abcDEF123ghiJKL456mnoPQR789"
CLIENT_SECRET = "s3cr3t-Value-ABCDEFGHIJ-9876"
INNOCENT_LOOKING = "plainword98765x"  # no pattern would catch this, only registration does


@pytest.fixture
def out() -> io.StringIO:
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    yield stream
    clear_registered()


def lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def assert_clean(stream: io.StringIO, *secrets: str) -> None:
    text = stream.getvalue()
    for s in secrets:
        assert s not in text, f"secret leaked: ...{s[-4:]}"


def test_output_is_json_with_basics(out: io.StringIO) -> None:
    get_logger("test").info("hello", strategy_id="s1", broker="dhan")
    (rec,) = lines(out)
    assert rec["event"] == "hello"
    assert rec["level"] == "info"
    assert rec["broker"] == "dhan"
    assert "timestamp" in rec


def test_secret_field_names_masked(out: io.StringIO) -> None:
    get_logger().info(
        "connect",
        api_key=API_KEY,
        access_token=ACCESS_TOKEN,
        client_secret=CLIENT_SECRET,
        password="hunter2hunter2",
    )
    (rec,) = lines(out)
    assert rec["api_key"] == "****" + API_KEY[-4:]
    assert rec["password"] == "****" + "hunter2hunter2"[-4:]
    assert_clean(out, API_KEY, ACCESS_TOKEN, CLIENT_SECRET, "hunter2hunter2")


def test_nested_structures_masked(out: io.StringIO) -> None:
    get_logger().info(
        "payload",
        request={"headers": {"access-token": ACCESS_TOKEN}, "body": [{"api_key": API_KEY}]},
    )
    assert_clean(out, API_KEY, ACCESS_TOKEN)


def test_secret_inside_message_text(out: io.StringIO) -> None:
    get_logger().info(f"calling broker with key {API_KEY} and token {ACCESS_TOKEN}")
    assert_clean(out, API_KEY, ACCESS_TOKEN)


def test_registered_secret_masked_under_any_name(out: io.StringIO) -> None:
    register_secret(INNOCENT_LOOKING)
    get_logger().info("odd", note=f"value is {INNOCENT_LOOKING}", items=[INNOCENT_LOOKING])
    get_logger().info(INNOCENT_LOOKING)
    assert_clean(out, INNOCENT_LOOKING)


def test_stdlib_library_logs_masked(out: io.StringIO) -> None:
    logging.getLogger("httpx").info("GET https://api.example.com/x?access_token=%s", ACCESS_TOKEN)
    logging.getLogger("uvicorn.error").warning("bad key %s", API_KEY)
    assert_clean(out, API_KEY, ACCESS_TOKEN)
    assert len(lines(out)) == 2


def test_exception_text_masked(out: io.StringIO) -> None:
    register_secret(CLIENT_SECRET)
    try:
        raise RuntimeError(f"auth failed for {CLIENT_SECRET}")
    except RuntimeError:
        get_logger().exception("broker error")
    assert_clean(out, CLIENT_SECRET)


def test_order_ref_uuid_not_masked(out: io.StringIO) -> None:
    ref = str(uuid.uuid4())
    get_logger().info("order placed", order_ref=ref, strategy_id="orb-1", broker="dhan")
    (rec,) = lines(out)
    assert rec["order_ref"] == ref


def test_normal_text_not_masked(out: io.StringIO) -> None:
    get_logger("app.brokers.dhan").info(
        "candle closed", symbol="RELIANCE", timeframe="5m", template_key="orb", qty=10
    )
    (rec,) = lines(out)
    assert rec["symbol"] == "RELIANCE"
    assert rec["template_key"] == "orb"
    assert rec["logger"] == "app.brokers.dhan"


@pytest.mark.parametrize(
    "name, secret",
    [
        ("api_key", True),
        ("apiKey", True),
        ("client_secret", True),
        ("access_token", True),
        ("Authorization", True),
        ("password", True),
        ("totp_secret_enc", True),
        ("encryption_key", True),
        ("template_key", False),
        ("symbol", False),
        ("order_ref", False),
        ("broker", False),
    ],
)
def test_is_secret_name(name: str, secret: bool) -> None:
    assert is_secret_name(name) is secret


def test_mask_value_shapes() -> None:
    assert mask_value("abcdefghijkl") == "****ijkl"
    assert mask_value("short") == "****"
