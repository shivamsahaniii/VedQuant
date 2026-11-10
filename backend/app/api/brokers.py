"""Broker accounts per user: add, keys per purpose (trading / data), test, status, disconnect.

Every route only touches the current user's accounts (anything else is a 404).
Responses never contain a full secret: only `last4`.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.connections import auto_use_broker, release_broker
from app.api.deps import CurrentUser, DbSession, owned_by
from app.brokers import registry
from app.brokers.service import (
    CredentialError,
    credential_rows,
    field_specs,
    remove_credentials,
    run_connection_test,
    save_credentials,
)
from app.core.events import record_event
from app.core.security import decrypt
from app.models import BrokerAccount, User
from app.schemas.broker import (
    BrokerAccountOut,
    BrokerCreate,
    ConnectionTestOut,
    CredentialFieldOut,
    CredentialsIn,
    Purpose,
    PurposeOut,
)

router = APIRouter(prefix="/brokers", tags=["brokers"])

PURPOSES: tuple[Purpose, ...] = ("trading", "data")


@router.get("/available")
async def available_brokers(_: CurrentUser) -> list[dict[str, Any]]:
    return registry.available()


async def _get_owned(db: DbSession, user: User, account_id: uuid.UUID) -> BrokerAccount:
    acct = await db.scalar(owned_by(BrokerAccount, user).where(BrokerAccount.id == account_id))
    if acct is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Broker account not found")
    return acct


async def _out(db: DbSession, acct: BrokerAccount) -> BrokerAccountOut:
    cls = registry.get_adapter_class(acct.broker)
    rows = {(r.purpose, r.field): r for r in await credential_rows(db, acct)}
    creds: dict[str, PurposeOut] = {}
    for purpose in PURPOSES:
        specs = field_specs(acct.broker, purpose)
        fields = []
        for f in specs:
            row = rows.get((purpose, f.name))
            value = None
            if row is not None and not f.secret:  # e.g. client id: safe to show
                value = decrypt(row.value_enc)
            fields.append(
                CredentialFieldOut(
                    name=f.name,
                    label=f.label,
                    secret=f.secret,
                    required=f.required,
                    saved=row is not None,
                    last4=row.last4 if (row is not None and f.secret) else None,
                    value=value,
                    updated_at=row.updated_at if row is not None else None,
                )
            )
        complete = bool(specs) and all(x.saved for x in fields if x.required)
        creds[purpose] = PurposeOut(fields=fields, complete=complete, needs_credentials=bool(specs))
    return BrokerAccountOut(
        id=acct.id,
        broker=acct.broker,
        broker_name=cls.display_name,
        is_paper=cls.is_paper,
        supports=sorted(cls.supports),
        label=acct.label,
        status=acct.status,
        last_checked_at=acct.last_checked_at,
        token_expires_at=acct.token_expires_at,
        last_error=acct.last_error,
        created_at=acct.created_at,
        credentials=creds,
    )


@router.get("", response_model=list[BrokerAccountOut])
async def list_accounts(user: CurrentUser, db: DbSession) -> list[BrokerAccountOut]:
    accts = (
        await db.scalars(owned_by(BrokerAccount, user).order_by(BrokerAccount.created_at))
    ).all()
    return [await _out(db, a) for a in accts]


@router.post("", response_model=BrokerAccountOut, status_code=status.HTTP_201_CREATED)
async def add_account(body: BrokerCreate, user: CurrentUser, db: DbSession) -> BrokerAccountOut:
    try:
        registry.get_adapter_class(body.broker)
    except registry.UnknownBroker:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown broker") from None
    acct = BrokerAccount(user_id=user.id, broker=body.broker, label=body.label, status="new")
    db.add(acct)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a broker with this name"
        ) from None
    await record_event(
        db, "broker", "broker added", user_id=user.id, broker=acct.broker, account_id=str(acct.id)
    )
    await db.commit()
    await db.refresh(acct)
    return await _out(db, acct)


@router.get("/{account_id}", response_model=BrokerAccountOut)
async def get_account(account_id: uuid.UUID, user: CurrentUser, db: DbSession) -> BrokerAccountOut:
    return await _out(db, await _get_owned(db, user, account_id))


@router.put("/{account_id}/credentials/{purpose}", response_model=BrokerAccountOut)
async def put_credentials(
    account_id: uuid.UUID, purpose: Purpose, body: CredentialsIn, user: CurrentUser, db: DbSession
) -> BrokerAccountOut:
    acct = await _get_owned(db, user, account_id)
    try:
        await save_credentials(db, acct, purpose, body.fields)
    except CredentialError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await record_event(
        db,
        "broker",
        f"{purpose} keys saved",
        user_id=user.id,
        broker=acct.broker,
        account_id=str(acct.id),
        fields=sorted(body.fields),  # names only, never values
    )
    await db.commit()
    await db.refresh(acct)
    return await _out(db, acct)


@router.delete("/{account_id}/credentials/{purpose}", response_model=BrokerAccountOut)
async def delete_credentials(
    account_id: uuid.UUID, purpose: Purpose, user: CurrentUser, db: DbSession
) -> BrokerAccountOut:
    acct = await _get_owned(db, user, account_id)
    await remove_credentials(db, acct, purpose)
    await record_event(
        db, "broker", f"{purpose} keys removed", user_id=user.id, account_id=str(acct.id)
    )
    await db.commit()
    await db.refresh(acct)
    return await _out(db, acct)


@router.post("/{account_id}/test", response_model=ConnectionTestOut)
async def test_account(
    account_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ConnectionTestOut:
    acct = await _get_owned(db, user, account_id)
    report = await run_connection_test(db, acct)
    switched: list[str] = []
    if report.ok and report.purpose_ok.get("data", True) and acct.status == "connected":
        switched = await auto_use_broker(db, user, acct.broker)
    await record_event(
        db,
        "broker",
        "connection test",
        user_id=user.id,
        level="info" if report.ok else "warning",
        broker=acct.broker,
        account_id=str(acct.id),
        ok=report.ok,
        purpose_ok=report.purpose_ok,
    )
    await db.commit()
    await db.refresh(acct)
    message = acct.last_error or report.message
    if switched:
        message += f" Real prices for {' and '.join(switched)} now come from this account."
    return ConnectionTestOut(
        ok=report.ok,
        message=message,
        purpose_ok=report.purpose_ok,
        funds_available=report.funds.available if report.funds else None,
        token_expires_at=report.token_expires_at,
        account=await _out(db, acct),
    )


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(account_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Disconnect = delete the account and every stored credential for it."""
    acct = await _get_owned(db, user, account_id)
    await record_event(
        db,
        "broker",
        "broker disconnected",
        user_id=user.id,
        broker=acct.broker,
        account_id=str(acct.id),
    )
    await db.delete(acct)
    await db.flush()
    await release_broker(db, user, acct.broker)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
