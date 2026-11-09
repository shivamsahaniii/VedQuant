"""Async SQLAlchemy engine and session."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    extra: dict[str, Any] = (
        {"poolclass": NullPool} if settings.db_null_pool else {"pool_pre_ping": True}
    )
    return create_async_engine(
        settings.database_url,
        **extra,
        # Store/compare timestamps in UTC; market-time conversion happens at the edges.
        connect_args={"server_settings": {"timezone": "UTC"}},
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
