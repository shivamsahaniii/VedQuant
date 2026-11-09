"""Structured JSON logging with secret masking.

Every log line, from our code (structlog) and from libraries (stdlib logging: uvicorn,
httpx, sqlalchemy, ...), passes through `mask_secrets` before it is written.

Three layers of protection:
1. Fields whose *name* looks secret (api_key, access_token, password, ...) are masked.
2. Exact values registered with `register_secret()` (every decrypted broker credential)
   are masked wherever they appear, under any field name or inside any message.
3. Long token-like strings (and JWTs) inside any string are masked. UUIDs are kept,
   because `order_ref` must stay readable.

Masked form: `****` + last 4 characters (or just `****` for very short values).
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from collections.abc import Iterable, MutableMapping
from typing import Any, TextIO

import structlog

MASK = "****"

# Field-name parts (split on "_" / "-") that always mean "secret".
_SECRET_NAME_PARTS = frozenset(
    {
        "secret",
        "token",
        "password",
        "passwd",
        "pwd",
        "authorization",
        "totp",
        "otp",
        "pin",
        "cookie",
        "credential",
        "credentials",
        "apikey",
        "jwt",
        "signature",
    }
)
# Names ending in "key" are secret unless listed here.
_SAFE_KEY_NAMES = frozenset({"template_key", "sort_key", "cache_key", "key_id", "broker_key"})

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
# 20+ chars of token alphabet. Checked further in `_mask_token_like`.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-+/=.]{20,}")

_registered: set[str] = set()
_registered_lock = threading.Lock()
_MIN_REGISTERED_LEN = 6  # avoid masking every "1234" in the logs


def mask_value(value: object) -> str:
    """`****` + last 4 chars. Values of 8 chars or fewer are fully masked."""
    s = str(value)
    if len(s) <= 8:
        return MASK
    return MASK + s[-4:]


def register_secret(value: str | None) -> None:
    """Mask this exact value everywhere in the logs from now on."""
    if value and len(value) >= _MIN_REGISTERED_LEN:
        with _registered_lock:
            _registered.add(value)


def unregister_secret(value: str | None) -> None:
    if value:
        with _registered_lock:
            _registered.discard(value)


def is_secret_name(name: str) -> bool:
    n = name.lower()
    if n in _SAFE_KEY_NAMES:
        return False
    parts = set(re.split(r"[_\-\s.]+", n))
    if parts & _SECRET_NAME_PARTS:
        return True
    return n.endswith("key") or n.endswith("_key")


def _mask_token_like(match: re.Match[str]) -> str:
    s = match.group(0)
    core = s.strip(".-_/=+")
    if _UUID_RE.match(core):
        return s
    has_alpha = any(c.isalpha() for c in core)
    has_digit = any(c.isdigit() for c in core)
    # Dotted/slashed things like module paths or URLs are not tokens unless mixed alnum.
    if not (has_alpha and has_digit):
        return s
    if (
        "." in core
        and not _JWT_RE.fullmatch(core)
        and all(p.isidentifier() for p in core.split(".") if p)
    ):
        return s  # e.g. "app.brokers.dhan_v2.adapter"
    return mask_value(core)


def mask_string(s: str) -> str:
    with _registered_lock:
        known = sorted(_registered, key=len, reverse=True)
    for secret in known:
        if secret in s:
            s = s.replace(secret, mask_value(secret))
    s = _JWT_RE.sub(lambda m: mask_value(m.group(0)), s)
    return _TOKEN_RE.sub(_mask_token_like, s)


def mask_any(value: Any, name: str | None = None) -> Any:
    if name is not None and is_secret_name(name) and value not in (None, ""):
        if isinstance(value, (dict, list, tuple, set)):
            return mask_any(value)
        return mask_value(value)
    if isinstance(value, str):
        return mask_string(value)
    if isinstance(value, dict):
        return {k: mask_any(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [mask_any(v) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return mask_string(str(value))


def mask_secrets(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """structlog processor."""
    for k in list(event_dict.keys()):
        event_dict[k] = mask_any(event_dict[k], k)
    return event_dict


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def configure_logging(level: str | int = "INFO", stream: TextIO | None = None) -> None:
    """Send all logs (structlog + stdlib) as masked JSON lines to `stream` (default stdout)."""
    shared = _shared_processors()

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            mask_secrets,  # last step before rendering: nothing escapes it
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Library loggers propagate to root so they get the same masking.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "sqlalchemy"):
        lib = logging.getLogger(name)
        lib.handlers = []
        lib.propagate = True
        lib.disabled = False  # e.g. after alembic's fileConfig disabled it


def get_logger(name: str | None = None, **initial: Any) -> structlog.stdlib.BoundLogger:
    log: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return log.bind(**initial) if initial else log


def registered_count() -> int:  # for tests/diagnostics only
    with _registered_lock:
        return len(_registered)


def clear_registered(values: Iterable[str] | None = None) -> None:  # tests only
    with _registered_lock:
        if values is None:
            _registered.clear()
        else:
            _registered.difference_update(values)
