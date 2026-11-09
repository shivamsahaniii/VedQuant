"""Test setup.

- Throwaway secrets, so tests never need (or read) a real .env.
- A separate database (`vedquant_test`), created and migrated once per test run.
  Tests that use the `db` fixture are skipped if Postgres is not running.
"""

import os

from cryptography.fernet import Fernet

os.environ["APP_ENV"] = "test"
os.environ["TRADING_MODE"] = "paper"
os.environ["DB_NULL_POOL"] = "true"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["JWT_SECRET"] = "test-only-jwt-secret-" + "x" * 32
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://vedquant:vedquant@localhost:5432/vedquant_test"
)

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DB_URL = os.environ["DATABASE_URL"]
# Shared market tables are truncated too; platform_settings is re-seeded by migrations only.
_TRUNCATE = "TRUNCATE users, instruments, candles, event_log RESTART IDENTITY CASCADE"


def _plain_dsn(db: str) -> str:
    base = TEST_DB_URL.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + "/" + db


async def _ensure_test_db() -> None:
    name = TEST_DB_URL.rsplit("/", 1)[1]
    conn = await asyncpg.connect(_plain_dsn("postgres"), timeout=3)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def migrated_db() -> str:
    try:
        asyncio.run(_ensure_test_db())
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        pytest.skip(f"Postgres not available for DB tests: {exc}")

    from alembic.config import Config

    from alembic import command

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
    return TEST_DB_URL


@pytest.fixture
async def db(migrated_db: str) -> AsyncIterator[AsyncSession]:
    """A session on a clean test database. Data is wiped after every test."""
    engine = create_async_engine(migrated_db, poolclass=NullPool)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
        async with engine.begin() as conn:
            await conn.execute(text(_TRUNCATE))
        await engine.dispose()
