"""Shared async Redis client (live quotes, events)."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings

_client: Any = None


def get_redis() -> Any:
    global _client
    if _client is None:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def set_redis(client: Any) -> None:
    """Tests: swap in a fake client."""
    global _client
    _client = client
