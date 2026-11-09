"""Sign up, log in, current user."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.events import record_event
from app.core.rate_limit import RateLimiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models import PlatformSetting, User
from app.schemas.auth import LoginIn, SignupIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# 5 failed logins per email+IP per 15 minutes.
login_limiter = RateLimiter(max_attempts=5, window_seconds=15 * 60)

# Used when the email doesn't exist, so a failed login takes the same time either way.
_DUMMY_HASH = hash_password("dummy-password-for-timing")

_BAD_LOGIN = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")


def _token_out(user: User) -> TokenOut:
    minutes = get_settings().jwt_expire_minutes
    return TokenOut(access_token=create_access_token(user.id), expires_in=minutes * 60)


@router.post("/signup", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupIn, db: DbSession) -> TokenOut:
    setting = await db.get(PlatformSetting, "signups_open")
    if setting is not None and setting.value is False:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-ups are closed")

    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from None

    await record_event(db, "auth", "signup", user_id=user.id)
    await db.commit()
    return _token_out(user)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, db: DbSession) -> TokenOut:
    ip = request.client.host if request.client else "unknown"
    key = f"{body.email}|{ip}"
    if login_limiter.is_blocked(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts, try again later"
        )

    user = await db.scalar(select(User).where(User.email == body.email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)

    if user is None or not ok:
        login_limiter.hit(key)
        await record_event(
            db,
            "auth",
            "login failed",
            user_id=user.id if user else None,
            level="warning",
            ip=ip,
        )
        await db.commit()
        raise _BAD_LOGIN

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")

    login_limiter.reset(key)
    await record_event(db, "auth", "login", user_id=user.id, ip=ip)
    await db.commit()
    return _token_out(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
