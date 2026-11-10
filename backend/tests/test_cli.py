"""Admin command line: set an account's password / login email."""

import contextlib

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.core import security
from app.models import User


@pytest.fixture
def cli_db(db: AsyncSession, monkeypatch):
    @contextlib.asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(cli, "get_sessionmaker", lambda: session)
    return db


async def _user(db, email, pw="old-password-123"):
    u = User(email=email, password_hash=security.hash_password(pw))
    db.add(u)
    await db.commit()
    return u


async def test_set_password_and_email(cli_db):
    u = await _user(cli_db, "demo@example.com")
    assert (
        await cli.set_password("Demo@Example.com ", "a-new-strong-password") == "demo@example.com"
    )
    await cli_db.refresh(u)
    assert security.verify_password("a-new-strong-password", u.password_hash)
    assert not security.verify_password("old-password-123", u.password_hash)

    assert (
        await cli.set_password("demo@example.com", "another-strong-pw-1", "Me@Mail.com")
        == "me@mail.com"
    )
    await cli_db.refresh(u)
    assert u.email == "me@mail.com" and u.role == "user"


async def test_set_password_unknown_or_taken_email(cli_db):
    await _user(cli_db, "a@example.com")
    await _user(cli_db, "b@example.com")
    assert await cli.set_password("nobody@example.com", "a-new-strong-password") is None
    with pytest.raises(ValueError, match="already used"):
        await cli.set_password("a@example.com", "a-new-strong-password", "b@example.com")
