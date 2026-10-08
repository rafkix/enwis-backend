"""Auth-module constants."""

from __future__ import annotations

OTP_LENGTH: int = 6
OTP_EXPIRE_SECONDS: int = 300  # 5 minutes

# Redis key prefixes
OTP_PREFIX: str = "otp"
REFRESH_TOKEN_PREFIX: str = "refresh"
