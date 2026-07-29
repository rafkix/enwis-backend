from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────


class AdminUserSummary(BaseModel):
    total: int = 0
    active: int = 0
    blocked: int = 0
    pending: int = 0
    new_today: int = 0
    new_this_week: int = 0


class AdminPaymentSummary(BaseModel):
    pending: int = 0
    waiting_for_review: int = 0
    approved: int = 0
    rejected: int = 0
    expired: int = 0
    cancelled: int = 0
    total_revenue: int = 0


class AdminSubscriptionSummary(BaseModel):
    active: int = 0
    by_tier: dict[str, int] = Field(default_factory=dict)


class AdminContentSummary(BaseModel):
    total_tests: int = 0
    total_questions: int = 0
    total_exams: int = 0
    total_attempts: int = 0
    total_certificates: int = 0


class AdminDashboardResponse(BaseModel):
    users: AdminUserSummary
    payments: AdminPaymentSummary
    subscriptions: AdminSubscriptionSummary
    content: AdminContentSummary


# ─────────────────────────────────────────────────────────────────
# User management
# ─────────────────────────────────────────────────────────────────


class AdminUserListItem(BaseModel):
    id: UUID
    public_id: str
    email: str | None
    username: str
    full_name: str | None
    phone: str | None
    status: str
    is_active: bool
    is_verified: bool
    roles: list[str] = Field(default_factory=list)
    subscription_tier: str
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}

    @field_validator("roles", mode="before")
    @classmethod
    def coerce_roles(cls, v):
        if not v:
            return []
        return [r.name if hasattr(r, "name") else str(r) for r in v]

    @field_validator("status", mode="before")
    @classmethod
    def coerce_status(cls, v):
        return v.value if hasattr(v, "value") else str(v)


class AdminUserListResponse(BaseModel):
    items: list[AdminUserListItem]
    total: int
    page: int
    per_page: int
    total_pages: int


class UpdateUserStatusRequest(BaseModel):
    status: str = Field(..., description="pending | active | blocked")
    reason: str | None = Field(None, max_length=500)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"pending", "active", "blocked"}
        if v.lower() not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return v.lower()


class UpdateUserRolesRequest(BaseModel):
    roles: list[str] = Field(..., min_length=1)


# ─────────────────────────────────────────────────────────────────
# Payment moderation
# ─────────────────────────────────────────────────────────────────


class AdminApprovePaymentRequest(BaseModel):
    note: str | None = Field(None, max_length=500)


class AdminRejectPaymentRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


# ─────────────────────────────────────────────────────────────────
# Audit logs
# ─────────────────────────────────────────────────────────────────


class AdminAuditLogResponse(BaseModel):
    id: UUID
    admin_id: UUID | None
    action: str
    target_type: str
    target_id: str | None
    detail: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogResponse]
    total: int
    page: int
    per_page: int
    total_pages: int
