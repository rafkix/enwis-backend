import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9._]+$")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    # Faqat register_verify javobida to'ldiriladi (login/refresh/social
    # oqimlarida None qoladi) — chunki foydalanuvchi buni faqat SHU yerda,
    # akkaunt birinchi marta yaratilganda bilib olishi mumkin. Avval hech
    # qayerda ko'rsatilmagani uchun odamlar avtomatik generatsiya qilingan
    # login'ini umuman bilmay qolib, keyinchalik kira olmay qolishardi.
    username: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class SocialProvider(StrEnum):
    GOOGLE = "google"
    TELEGRAM = "telegram"


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, description="Username")
    password: str = Field(..., min_length=1)


class RegisterSendCodeRequest(BaseModel):
    """Step 1 of the one-time app.enwis.uz registration."""

    full_name: str = Field(..., min_length=3, max_length=255, description="Ism va familiya")
    phone: str = Field(..., min_length=7, max_length=20)
    password: str = Field(..., min_length=8)


class RegisterVerifyRequest(BaseModel):
    """Step 2: confirm the SMS code. Login is auto-generated from the
    full name given in step 1 — nothing else is needed here."""

    phone: str = Field(..., min_length=7, max_length=20)
    code: str = Field(..., min_length=4, max_length=8)


class SocialLoginRequest(BaseModel):
    provider: SocialProvider
    id_token: str | None = None
    telegram_data: dict | None = None

    @model_validator(mode="after")
    def check_provider_data(self):
        if self.provider == SocialProvider.GOOGLE and not self.id_token:
            raise ValueError("id_token is required for Google login")
        if self.provider == SocialProvider.TELEGRAM and not self.telegram_data:
            raise ValueError("telegram_data is required for Telegram login")
        return self


class TelegramWebAppAuthRequest(BaseModel):
    """Auth for web3.enwis.uz (Telegram Mini App). `init_data` is the
    raw string from `Telegram.WebApp.initData` — send it EXACTLY as
    provided by the Telegram client SDK, do not parse/modify it."""

    init_data: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    id: UUID
    public_id: str
    email: str | None = None
    username: str
    phone: str | None = None
    full_name: str | None = None
    avatar: str | None = None
    telegram_id: str | None = None
    is_google_verified: bool = False
    is_telegram_verified: bool = False
    is_active: bool
    is_verified: bool
    phone_verified: bool
    status: str
    roles: list[str] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MeResponse(BaseModel):
    id: UUID
    public_id: str
    full_name: str | None = None
    username: str
    email: str | None = None
    phone: str | None = None
    phone_verified: bool = False
    telegram_id: str | None = None
    avatar: str | None = None
    is_google_verified: bool = False
    is_telegram_verified: bool = False
    is_verified: bool
    is_active: bool
    status: str
    roles: list[str] = []
    meta: dict | None = None
    has_active_subscription: bool = False

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)

    @model_validator(mode="after")
    def passwords_must_differ(self):
        if self.current_password == self.new_password:
            raise ValueError("New password must be different from the current password")
        return self


class SetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class SessionResponse(BaseModel):
    id: UUID
    ip_address: str | None = None
    user_agent: str | None = None
    is_revoked: bool
    expires_at: datetime
    last_used_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class RevokeSessionRequest(BaseModel):
    session_id: str


class SendPhoneCodeRequest(BaseModel):
    phone: str = Field(..., min_length=7, max_length=20)


class VerifyPhoneRequest(BaseModel):
    phone: str = Field(..., min_length=7, max_length=20)
    code: str = Field(..., min_length=4, max_length=8)


class RegisterPhoneVerifyResponse(BaseModel):
    success: bool = True
    message: str
    ticket: str


class LinkGoogleRequest(BaseModel):
    id_token: str


class LinkTelegramRequest(BaseModel):
    telegram_data: dict


class LinkedAccountResponse(BaseModel):
    provider: SocialProvider
    linked: bool
    email: str | None = None


class LogoutResponse(BaseModel):
    success: bool
    message: str


class MessageResponse(BaseModel):
    success: bool = True
    message: str
