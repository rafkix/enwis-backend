from __future__ import annotations

import re
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.auth.models import UserStatus


class UserMeta(BaseModel):
    version: int = 1
    bio: str | None = Field(None, max_length=500)
    birth_date: date | None = None


class UserResponse(BaseModel):
    id: UUID
    public_id: str
    email: str | None = None
    username: str
    full_name: str | None = None
    phone: str | None = None
    phone_verified: bool = False
    avatar: str | None = None
    is_google_verified: bool = False
    is_telegram_verified: bool = False
    is_verified: bool
    is_active: bool
    status: UserStatus
    roles: list[str] = Field(default_factory=list)
    meta: UserMeta | None = None
    has_password: bool = False
    requires_phone_verification: bool = False
    requires_password_setup: bool = False
    referral_code: str | None = None
    xp: int = 0
    level: int = 1
    streak: int = 0
    is_teacher: bool = False
    teacher_verified_at: datetime | None = None
    subscription_tier: str = "FREE"
    subscription_status: str | None = None
    subscription_expires_at: datetime | None = None
    has_active_subscription: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiResponse(BaseModel):
    success: bool = True
    message: str = "OK"
    data: dict | list | None = None


class UpdateUserSchema(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    username: str | None = Field(None, min_length=3, max_length=30)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=20)
    meta: UserMeta | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9._]+$", v):
            raise ValueError("Username must contain only letters, numbers, underscores, and dots")
        return v.lower()

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", v):
            raise ValueError("Invalid email format")
        return v.strip().lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if v is None:
            return v
        cleaned = re.sub(r"\s+", "", v)
        if not re.match(r"^\+?[0-9]{7,15}$", cleaned):
            raise ValueError("Invalid phone number format")
        return cleaned


class UpdateAvatarSchema(BaseModel):
    avatar_url: str = Field(..., min_length=10)

    @field_validator("avatar_url")
    @classmethod
    def validate_url(cls, v):
        if not re.match(r"^https?://", v):
            raise ValueError("Avatar URL must start with http:// or https://")
        return v


class ChangePasswordSchema(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        if " " in v:
            raise ValueError("Password must not contain spaces")
        return v


class SetPasswordSchema(BaseModel):
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        if " " in v:
            raise ValueError("Password must not contain spaces")
        return v


class DeviceResponse(BaseModel):
    id: UUID
    ip_address: str | None = None
    user_agent: str | None = None
    expires_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReferralSummary(BaseModel):
    referral_code: str
    invited_count: int
    referral_url: str | None = None


class RevokeOthersSchema(BaseModel):
    current_session_id: str = Field(..., min_length=1)


class DeleteAccountSchema(BaseModel):
    password: str | None = None


class PhoneUpdateRequestSchema(BaseModel):
    phone: str = Field(..., min_length=7, max_length=20)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"\s+", "", v)
        if not re.match(r"^\+?[0-9]{7,15}$", cleaned):
            raise ValueError("Invalid phone number format")
        return cleaned


class PhoneUpdateVerifySchema(BaseModel):
    phone: str = Field(..., min_length=7, max_length=20)
    code: str = Field(..., min_length=4, max_length=8)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"\s+", "", v)
        if not re.match(r"^\+?[0-9]{7,15}$", cleaned):
            raise ValueError("Invalid phone number format")
        return cleaned


class SessionResponse(BaseModel):
    id: UUID
    ip_address: str | None = None
    user_agent: str | None = None
    device_name: str | None = None
    is_revoked: bool = False
    is_current: bool = False
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanInfo(BaseModel):
    tier: str = "free"
    status: str = "active"
    expires_at: datetime | None = None
    features: list[str] = Field(default_factory=list)
    # AI usage info
    ai_questions_used: int = 0
    ai_questions_monthly_limit: int = 0  # 0 = yo'q, -1 = cheksiz
    ai_questions_reset_at: datetime | None = None


class AccountSummary(BaseModel):
    user: UserResponse
    sessions: list[SessionResponse] = Field(default_factory=list)
    devices: list[DeviceResponse] = Field(default_factory=list)
    plan: PlanInfo = Field(default_factory=PlanInfo)
    referral: ReferralSummary | None = None
    settings: dict = Field(default_factory=dict)


class UserSettingsSchema(BaseModel):
    language: str | None = Field(None, min_length=2, max_length=10)
    timezone: str | None = Field(None, min_length=1, max_length=50)
    email_notifications: bool | None = None
    sms_notifications: bool | None = None
    push_notifications: bool | None = None
    marketing_consent: bool | None = None
