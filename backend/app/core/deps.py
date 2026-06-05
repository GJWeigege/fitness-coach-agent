import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import resolve_user_permissions
from app.auth.tokens import decode_access_token
from app.db.models import User
from app.db.session import get_db_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="缺少认证信息。")
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="token 用户信息无效。") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用。")
    return user


def get_user_permissions(user: User) -> set[str]:
    return resolve_user_permissions(role=user.role, custom_permissions=user.custom_permissions)


def require_permissions(*required: str):
    async def checker(user: User = Depends(get_current_user)) -> User:
        permissions = get_user_permissions(user)
        missing = [item for item in required if item not in permissions]
        if missing:
            raise HTTPException(status_code=403, detail=f"权限不足，缺少: {', '.join(missing)}")
        return user

    return checker
