from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from src.api.deps import CurrentUser, DbSession
from src.api.schemas import AuthStatusOut, AuthUserOut, ChangePasswordRequest, LoginRequest
from src.auth.exceptions import AuthError
from src.auth.service import (
    change_password,
    clear_session_cookie,
    login,
    logout,
    read_session_token,
    set_session_cookie,
    setup_complete,
)

router = APIRouter(tags=["auth"])


def _user_out(user) -> AuthUserOut:
    return AuthUserOut(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        must_change_password=user.must_change_password,
    )


@router.get("/status", response_model=AuthStatusOut)
async def auth_status(db: DbSession) -> AuthStatusOut:
    return AuthStatusOut(setup_complete=await setup_complete(db))


@router.post("/login", response_model=AuthUserOut)
async def auth_login(
    body: LoginRequest, request: Request, response: Response, db: DbSession
) -> AuthUserOut:
    try:
        user, token = await login(
            db,
            username=body.username.strip(),
            password=body.password,
            request=request,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    set_session_cookie(response, token)
    return _user_out(user)


@router.get("/me", response_model=AuthUserOut)
async def auth_me(user: CurrentUser) -> AuthUserOut:
    return _user_out(user)


@router.post("/logout")
async def auth_logout(request: Request, response: Response, db: DbSession) -> dict[str, bool]:
    token = read_session_token(request)
    if token:
        await logout(db, token)
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/change-password", response_model=AuthUserOut)
async def auth_change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> AuthUserOut:
    try:
        updated = await change_password(
            db,
            user,
            current_password=body.current_password,
            new_password=body.new_password,
            keep_token=read_session_token(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return _user_out(updated)
