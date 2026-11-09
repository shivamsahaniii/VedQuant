from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models import BrokerAccount, BrokerCredential, Candle, EventLog, User, UserSetting


async def make_user(db: AsyncSession, email: str = "a@example.com") -> User:
    user = User(email=email, password_hash=security.hash_password("long-enough-pw"))
    db.add(user)
    await db.flush()
    return user


async def test_new_user_defaults_to_paper_and_user_role(db: AsyncSession) -> None:
    user = await make_user(db)
    await db.commit()
    await db.refresh(user)
    assert user.trading_mode == "paper"
    assert user.role == "user"
    assert user.is_active is True
    assert user.created_at.tzinfo is not None


async def test_duplicate_email_rejected(db: AsyncSession) -> None:
    await make_user(db, "same@example.com")
    with pytest.raises(IntegrityError):
        await make_user(db, "same@example.com")


async def test_email_must_be_lowercase(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await make_user(db, "Mixed@Example.com")


async def test_invalid_trading_mode_rejected(db: AsyncSession) -> None:
    user = await make_user(db)
    user.trading_mode = "real"
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_credentials_stored_encrypted_and_split_by_purpose(db: AsyncSession) -> None:
    user = await make_user(db)
    acct = BrokerAccount(user_id=user.id, broker="dhan", label="Dhan main")
    db.add(acct)
    await db.flush()
    for purpose, value in (
        ("trading", "trade-token-ABCDEFGH1234"),
        ("data", "data-token-ZYXW9876"),
    ):
        db.add(
            BrokerCredential(
                user_id=user.id,
                broker_account_id=acct.id,
                purpose=purpose,
                field="access_token",
                value_enc=security.encrypt(value),
                last4=security.last4(value),
            )
        )
    await db.commit()

    raw = (await db.execute(text("SELECT value_enc FROM broker_credentials"))).scalars().all()
    assert len(raw) == 2
    assert all(b"token" not in bytes(r) for r in raw)

    # Same field under the same purpose twice is not allowed.
    db.add(
        BrokerCredential(
            user_id=user.id,
            broker_account_id=acct.id,
            purpose="data",
            field="access_token",
            value_enc=security.encrypt("x" * 20),
            last4="xxxx",
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_deleting_account_deletes_credentials(db: AsyncSession) -> None:
    user = await make_user(db)
    acct = BrokerAccount(user_id=user.id, broker="dhan", label="Dhan")
    db.add(acct)
    await db.flush()
    db.add(
        BrokerCredential(
            user_id=user.id,
            broker_account_id=acct.id,
            purpose="trading",
            field="client_id",
            value_enc=security.encrypt("1100001234"),
            last4="1234",
        )
    )
    await db.commit()
    await db.execute(text("DELETE FROM broker_accounts"))
    await db.commit()
    count = await db.scalar(select(func.count()).select_from(BrokerCredential))
    assert count == 0


async def test_deleting_user_deletes_everything_they_own(db: AsyncSession) -> None:
    user = await make_user(db)
    db.add(BrokerAccount(user_id=user.id, broker="paper", label="Paper"))
    db.add(UserSetting(user_id=user.id, key="data_broker", value="paper"))
    db.add(EventLog(user_id=user.id, type="auth", message="signed up"))
    await db.commit()
    await db.execute(text("DELETE FROM users"))
    await db.commit()
    for model in (BrokerAccount, UserSetting, EventLog):
        assert await db.scalar(select(func.count()).select_from(model)) == 0


async def test_candle_round_trip_keeps_decimals(db: AsyncSession) -> None:
    ts = datetime(2026, 11, 9, 3, 45, tzinfo=UTC)  # 09:15 IST
    db.add(
        Candle(
            exchange="NSE",
            symbol="RELIANCE",
            timeframe="5m",
            ts=ts,
            open=Decimal("2900.05"),
            high=Decimal("2910.50"),
            low=Decimal("2898.00"),
            close=Decimal("2905.25"),
            volume=12345,
        )
    )
    await db.commit()
    c = await db.scalar(select(Candle))
    assert c is not None
    assert isinstance(c.close, Decimal)
    assert c.close == Decimal("2905.2500")
    assert c.ts == ts


async def test_candle_bad_values_rejected(db: AsyncSession) -> None:
    db.add(
        Candle(
            exchange="NSE",
            symbol="X",
            timeframe="7m",
            ts=datetime.now(UTC),
            open=Decimal(1),
            high=Decimal(2),
            low=Decimal(1),
            close=Decimal(1),
            volume=1,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_candles_is_hypertable(db: AsyncSession) -> None:
    name = await db.scalar(
        text(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'candles'"
        )
    )
    assert name == "candles"
