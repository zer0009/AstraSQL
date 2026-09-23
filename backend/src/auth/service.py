from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.exceptions import AuthError
from src.auth.passwords import (
    hash_password,
    validate_new_password,
    verify_dummy_password,
    verify_password,
)
from src.auth.tokens import hash_session_token, new_session_token
from src.config.settings import get_settings
from src.storage.models import AuthSession, User

logger = logging.getLogger(__name__)

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
        path="/",
        max_age=settings.session_ttl_days * 86400,
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
    )


def read_session_token(request: Request) -> str | None:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        return None
    return token


async def bootstrap_admin(session: AsyncSession) -> bool:
    """Create the default admin if no users exist. Returns True if created."""
    count = await session.scalar(select(func.count()).select_from(User))
    if count:
        return False

    settings = get_settings()
    user = User(
        username=settings.default_admin_username,
        password_hash=hash_password(settings.default_admin_password),
        is_active=True,
        is_admin=True,
        must_change_password=True,
        failed_login_count=0,
    )
    session.add(user)
    await session.flush()
    logger.warning(
        "Default admin created (username=%s). Sign in and change the password immediately.",
        settings.default_admin_username,
    )
    return True


async def setup_complete(session: AsyncSession) -> bool:
    result = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.must_change_password.is_(False))
    )
    return bool(result)


async def login(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    request: Request,
) -> tuple[User, str]:
    now = _utcnow()
    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        verify_dummy_password(password)
        raise AuthError(401, "Invalid username or password")

    if user.locked_until and user.locked_until > now:
        raise AuthError(423, "Account locked. Try again later.")

    if not user.is_active or not verify_password(user.password_hash, password):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        await session.commit()
        raise AuthError(401, "Invalid username or password")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    token = new_session_token()
    ttl = timedelta(days=get_settings().session_ttl_days)
    row = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=now + ttl,
        last_seen_at=now,
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
        ip=_client_ip(request),
    )
    session.add(row)
    await session.flush()
    return user, token


async def get_user_for_token(
    session: AsyncSession,
    token: str,
    *,
    touch: bool = True,
) -> Optional[User]:
    now = _utcnow()
    token_hash = hash_session_token(token)
    row = await session.scalar(
        select(AuthSession)
        .options(selectinload(AuthSession.user))
        .where(AuthSession.token_hash == token_hash)
    )
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at <= now:
        return None
    user = row.user
    if user is None or not user.is_active:
        return None
    if touch:
        ttl = timedelta(days=get_settings().session_ttl_days)
        row.last_seen_at = now
        row.expires_at = now + ttl
    return user


async def current_session_row(
    session: AsyncSession, token: str
) -> Optional[AuthSession]:
    token_hash = hash_session_token(token)
    return await session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash)
    )


async def logout(session: AsyncSession, token: str) -> None:
    row = await current_session_row(session, token)
    if row is None or row.revoked_at is not None:
        return
    row.revoked_at = _utcnow()
    await session.flush()


async def change_password(
    session: AsyncSession,
    user: User,
    *,
    current_password: str,
    new_password: str,
    keep_token: str | None,
) -> User:
    settings = get_settings()
    if not verify_password(user.password_hash, current_password):
        raise AuthError(400, "Current password is incorrect")

    error = validate_new_password(
        new_password,
        default_password=settings.default_admin_password,
        current_password=current_password,
    )
    if error:
        raise AuthError(400, error)

    now = _utcnow()
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = now
    user.failed_login_count = 0
    user.locked_until = None

    keep_hash = hash_session_token(keep_token) if keep_token else None
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user.id)
        .where(AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if keep_hash:
        stmt = stmt.where(AuthSession.token_hash != keep_hash)
    await session.execute(stmt)
    await session.flush()
    return user
