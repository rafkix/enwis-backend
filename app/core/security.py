import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> tuple[bool, bool]:
    try:
        is_valid = pwd_context.verify(plain, hashed)
        needs_rehash = pwd_context.needs_update(hashed)
        return is_valid, needs_rehash
    except Exception:
        return False, False


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    )
    to_encode.update(
        {"exp": expire, "iat": datetime.now(UTC), "type": "access"}
    )
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.ALGORITHM)


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_DAYS)
    )
    to_encode.update(
        {"exp": expire, "iat": datetime.now(UTC), "type": "refresh"}
    )
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token yaroqsiz yoki muddati tugagan",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def hash_token_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_token_sha256(value: str, hashed: str) -> bool:
    expected = hash_token_sha256(value)
    return hmac.compare_digest(expected, hashed)


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def verify_otp(code: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_otp(code), hashed)
