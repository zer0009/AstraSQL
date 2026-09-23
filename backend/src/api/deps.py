from typing import Annotated, AsyncGenerator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.exceptions import PasswordChangeRequiredError
from src.auth.service import get_user_for_token, read_session_token
from src.storage.database import get_session
from src.storage.models import User


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(request: Request, db: DbSession) -> User:
    token = read_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = await get_user_for_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def require_ready_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.must_change_password:
        raise PasswordChangeRequiredError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
ReadyUser = Annotated[User, Depends(require_ready_user)]
