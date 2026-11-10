"""Admin command line.

    python -m app.cli create-admin you@example.com
    python -m app.cli set-password you@example.com                  # new password for an account
    python -m app.cli set-password old@example.com --email new@x.com   # and a new login email

The password is asked interactively (never pass it as an argument: it would land in shell history).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.core.events import record_event
from app.core.security import MIN_PASSWORD_LENGTH, hash_password
from app.models import User


async def create_admin(email: str, password: str) -> str:
    email = email.strip().lower()
    async with get_sessionmaker()() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(password), role="admin")
            db.add(user)
            action = "created"
        else:
            user.role = "admin"
            user.password_hash = hash_password(password)
            action = "promoted"
        await db.flush()
        await record_event(db, "auth", f"admin {action}", user_id=user.id)
        await db.commit()
        return action


async def set_password(email: str, password: str, new_email: str | None = None) -> str | None:
    """Set an existing account's password (and optionally its login email). Returns the login
    email, or None when there is no such account. Role, strategies and keys are untouched."""
    email = email.strip().lower()
    async with get_sessionmaker()() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            return None
        if new_email:
            new_email = new_email.strip().lower()
            if await db.scalar(select(User.id).where(User.email == new_email, User.id != user.id)):
                raise ValueError(f"{new_email} is already used by another account")
            user.email = new_email
        user.password_hash = hash_password(password)
        await record_event(db, "auth", "password set from the command line", user_id=user.id)
        await db.commit()
        return user.email


def _ask_password(label: str) -> str | None:
    pw = getpass.getpass(f"{label}: ")
    if len(pw) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters", file=sys.stderr)
        return None
    if getpass.getpass("Repeat password: ") != pw:
        print("Passwords do not match", file=sys.stderr)
        return None
    return pw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin", help="Create an admin user (or promote an existing one)")
    p.add_argument("email")
    p = sub.add_parser("set-password", help="Set a new password for an existing account")
    p.add_argument("email")
    p.add_argument("--email", dest="new_email", help="Also change the login email to this")
    args = parser.parse_args(argv)

    if args.cmd == "set-password":
        pw = _ask_password("New password")
        if pw is None:
            return 1
        try:
            login = asyncio.run(set_password(args.email, pw, args.new_email))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if login is None:
            print(f"No account with email {args.email.strip().lower()}", file=sys.stderr)
            return 1
        print(f"Password set. Log in as: {login}")
        return 0

    if args.cmd == "create-admin":
        pw = getpass.getpass("Admin password: ")
        if len(pw) < MIN_PASSWORD_LENGTH:
            print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters", file=sys.stderr)
            return 1
        if getpass.getpass("Repeat password: ") != pw:
            print("Passwords do not match", file=sys.stderr)
            return 1
        action = asyncio.run(create_admin(args.email, pw))
        print(f"Admin {action}: {args.email.strip().lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
