"""Broker accounts: credential storage (encrypted) and connection tests.

Secrets are encrypted before they touch the database and are only decrypted here, right
before an adapter needs them. API responses only ever carry `last4` for secret fields.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers.base import (
    BrokerAdapter,
    BrokerAuthError,
    BrokerCredentials,
    BrokerError,
    ConnectionReport,
    FieldSpec,
    Purpose,
)
from app.brokers.registry import create_adapter, get_adapter_class
from app.core.logging import mask_string
from app.core.security import decrypt, encrypt, last4
from app.models import BrokerAccount, BrokerCredential


class CredentialError(ValueError):
    """Submitted credential fields are invalid for this broker/purpose."""


def field_specs(broker: str, purpose: Purpose) -> list[FieldSpec]:
    return list(get_adapter_class(broker).credential_fields.get(purpose, []))


def validate_fields(broker: str, purpose: Purpose, values: dict[str, str]) -> dict[str, str]:
    """Only known fields, no empty values. Missing fields are allowed (kept from before)."""
    specs = {f.name: f for f in field_specs(broker, purpose)}
    if not specs:
        raise CredentialError(f"{broker} has no {purpose} credentials")
    clean: dict[str, str] = {}
    for name, value in values.items():
        if name not in specs:
            raise CredentialError(f"Unknown field for {broker} {purpose}: {name[:40]}")
        v = (value or "").strip()
        if not v:
            raise CredentialError(f"{specs[name].label} cannot be empty")
        if len(v) > 4096:
            raise CredentialError(f"{specs[name].label} is too long")
        clean[name] = v
    if not clean:
        raise CredentialError("No credential values were sent")
    return clean


async def save_credentials(
    db: AsyncSession, account: BrokerAccount, purpose: Purpose, values: dict[str, str]
) -> None:
    """Add or replace the given fields for one purpose. Other purpose is never touched."""
    clean = validate_fields(account.broker, purpose, values)
    existing = {
        c.field: c
        for c in (
            await db.scalars(
                select(BrokerCredential).where(
                    BrokerCredential.broker_account_id == account.id,
                    BrokerCredential.purpose == purpose,
                )
            )
        ).all()
    }
    now = datetime.now(UTC)
    for name, value in clean.items():
        row = existing.get(name)
        if row is None:
            db.add(
                BrokerCredential(
                    user_id=account.user_id,
                    broker_account_id=account.id,
                    purpose=purpose,
                    field=name,
                    value_enc=encrypt(value),
                    last4=last4(value),
                )
            )
        else:
            row.value_enc = encrypt(value)
            row.last4 = last4(value)
            row.updated_at = now
    # New keys have not been tested yet.
    account.status = "new"
    account.last_error = None


async def remove_credentials(db: AsyncSession, account: BrokerAccount, purpose: Purpose) -> None:
    await db.execute(
        delete(BrokerCredential).where(
            BrokerCredential.broker_account_id == account.id,
            BrokerCredential.purpose == purpose,
        )
    )
    account.status = "new"


async def credential_rows(db: AsyncSession, account: BrokerAccount) -> list[BrokerCredential]:
    return list(
        (
            await db.scalars(
                select(BrokerCredential).where(BrokerCredential.broker_account_id == account.id)
            )
        ).all()
    )


async def load_credentials(db: AsyncSession, account: BrokerAccount) -> BrokerCredentials:
    trading: dict[str, str] = {}
    data: dict[str, str] = {}
    for row in await credential_rows(db, account):
        target = trading if row.purpose == "trading" else data
        target[row.field] = decrypt(row.value_enc)
    return BrokerCredentials(trading=trading, data=data)


async def build_adapter(db: AsyncSession, account: BrokerAccount) -> BrokerAdapter:
    # live_enabled stays False here: connection tests never place orders.
    return create_adapter(account.broker, await load_credentials(db, account))


async def run_connection_test(db: AsyncSession, account: BrokerAccount) -> ConnectionReport:
    adapter = await build_adapter(db, account)
    try:
        report = await adapter.test_connection()
    except BrokerAuthError as exc:
        report = ConnectionReport(ok=False, message=str(exc))
    except BrokerError as exc:
        report = ConnectionReport(ok=False, message=str(exc))
    finally:
        await adapter.close()

    now = datetime.now(UTC)
    account.last_checked_at = now
    account.token_expires_at = report.token_expires_at
    if report.ok:
        account.status = "connected"
        account.last_error = None
    else:
        expired = report.token_expires_at is not None and report.token_expires_at < now
        account.status = "expired" if expired else "error"
        account.last_error = mask_string(report.message)[:500]
    return report
