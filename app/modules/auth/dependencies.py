from uuid import UUID

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.models import User

# Registered so FastAPI adds a bearer security scheme to the OpenAPI schema
# (this is what makes the "Authorize" button appear in /docs). auto_error=False
# because we still fall back to the access_token cookie below — the actual
# token value is re-read from the header/cookie in _extract_token either way.
bearer_scheme = HTTPBearer(auto_error=False)


def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization")
    if auth:
        parts = auth.split()
        if len(parts) != 2:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Authorization header is in the wrong format",
            )
        scheme, token = parts
        if scheme.lower() != "bearer":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer scheme required")
        return token

    token = request.cookies.get("access_token")
    if token:
        return token

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> User:
    token = _extract_token(request)

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.ALGORITHM],
        )
        user_id: str = payload.get("sub")

        if not user_id or not isinstance(user_id, str):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Token payload is incorrect"
            )

        token_type = payload.get("type")
        if token_type != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Access token required")
        user_uuid = UUID(user_id)

    except (JWTError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalid or expired") from None
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_uuid)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> User | None:
    try:
        token = _extract_token(request)
    except HTTPException:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.ALGORITHM],
        )
        user_id: str = payload.get("sub")
        if not user_id or not isinstance(user_id, str):
            return None
        if payload.get("type") != "access":
            return None
        user_uuid = UUID(user_id)
    except (JWTError, ValueError):
        return None

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_uuid)
    )
    return result.scalar_one_or_none()


async def get_active_user(
    user: User = Depends(get_current_user),
) -> User:
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User inactive")
    if user.status == "blocked":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User blocked")
    return user


async def get_verified_user(
    user: User = Depends(get_active_user),
) -> User:
    if not user.is_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Email not verified")
    return user


def require_roles(*role_names: str):
    for r in role_names:
        if not isinstance(r, str):
            raise ValueError(f"Invalid role: {r}.")

    async def checker(user: User = Depends(get_active_user)) -> User:
        user_roles = {role.name.upper() for role in (user.roles or [])}

        if not user_roles.intersection(r.upper() for r in role_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(role_names)}",
            )

        return user

    return checker
