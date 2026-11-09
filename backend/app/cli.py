"""Admin command line.

    python -m app.cli create-admin you@example.com

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin", help="Create an admin user (or promote an existing one)")
    p.add_argument("email")
    args = parser.parse_args(argv)

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
