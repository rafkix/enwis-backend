from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ── Teacher Package ───────────────────────────────────────────────────


class TeacherPackageResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    price: int
    currency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TeacherPackageUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    price: int | None = Field(None, ge=0)
    is_active: bool | None = None


class TeacherPurchaseResponse(BaseModel):
    id: UUID
    user_id: UUID
    package_id: UUID
    card_id: UUID | None = None
    amount: int
    currency: str
    payment_method: str | None
    payment_ref: str | None
    status: str
    receipt_image: bool = False
    reviewed_by_id: UUID | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    purchased_at: datetime

    model_config = {"from_attributes": True}


class TeacherPurchaseListResponse(BaseModel):
    items: list[TeacherPurchaseResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class PurchaseTeacherPackageRequest(BaseModel):
    payment_method: str = Field("manual_card", description="Payment method")
    payment_ref: str | None = None


class RejectTeacherPurchaseRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ApproveTeacherPurchaseRequest(BaseModel):
    note: str | None = Field(None, max_length=500)


# ── Pricing Plans ─────────────────────────────────────────────────────


class PricingPlanFeatureCreate(BaseModel):
    feature: str = Field(..., min_length=1, max_length=255)
    sort_order: int = 0


class PricingPlanFeatureResponse(BaseModel):
    id: UUID
    plan_id: UUID
    feature: str
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PricingPlanResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    price: int
    currency: str
    interval: str
    is_active: bool
    sort_order: int
    is_default: bool
    features: list[PricingPlanFeatureResponse] = []
    discount: DiscountInfo | None = None
    discounted_price: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PricingPlanListResponse(BaseModel):
    items: list[PricingPlanResponse]
    total: int


class PricingPlanAdminUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=50)
    description: str | None = None
    price: int | None = Field(None, ge=0)
    is_active: bool | None = None
    features: list[PricingPlanFeatureCreate] | None = None


class DiscountInfo(BaseModel):
    id: UUID
    name: str
    percentage: float
    start_date: datetime
    end_date: datetime
    is_active: bool


# ── Discount System ───────────────────────────────────────────────────


class DiscountCreate(BaseModel):
    plan_id: UUID
    name: str = Field(..., min_length=1, max_length=100)
    percentage: float = Field(..., ge=0, le=100)
    start_date: datetime
    end_date: datetime

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        return v

    @field_validator("percentage")
    @classmethod
    def validate_percentage(cls, v):
        if v <= 0 or v > 100:
            raise ValueError("Percentage must be between 0 and 100")
        return v


class DiscountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    percentage: float | None = Field(None, ge=0, le=100)
    start_date: datetime | None = None
    end_date: datetime | None = None
    is_active: bool | None = None


class DiscountResponse(BaseModel):
    id: UUID
    plan_id: UUID
    name: str
    percentage: float
    start_date: datetime
    end_date: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiscountListResponse(BaseModel):
    items: list[DiscountResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


# ── Promo Code System ─────────────────────────────────────────────────


class PromoCodeCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=50)
    discount_type: str = "percentage"
    discount_value: float = Field(..., ge=0)
    usage_limit: int = Field(0, ge=0)
    per_user_limit: int = Field(1, ge=1)
    is_active: bool = True
    valid_from: datetime
    valid_until: datetime
    minimum_amount: int = Field(0, ge=0)
    plan_ids: list[UUID] = []

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("discount_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("percentage", "fixed"):
            raise ValueError("discount_type must be 'percentage' or 'fixed'")
        return v

    @field_validator("discount_value")
    @classmethod
    def validate_value(cls, v, info):
        dtype = info.data.get("discount_type")
        if dtype == "percentage" and (v <= 0 or v > 100):
            raise ValueError("Percentage discount must be between 0 and 100")
        if dtype == "fixed" and v < 0:
            raise ValueError("Fixed discount must be >= 0")
        return v


class PromoCodeUpdate(BaseModel):
    code: str | None = Field(None, min_length=3, max_length=50)
    discount_type: str | None = None
    discount_value: float | None = Field(None, ge=0)
    usage_limit: int | None = Field(None, ge=0)
    per_user_limit: int | None = Field(None, ge=1)
    is_active: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    minimum_amount: int | None = Field(None, ge=0)
    plan_ids: list[UUID] | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return v.strip().upper()


class PromoCodeResponse(BaseModel):
    id: UUID
    code: str
    discount_type: str
    discount_value: float
    usage_limit: int
    used_count: int
    per_user_limit: int
    is_active: bool
    valid_from: datetime
    valid_until: datetime
    minimum_amount: int
    plans: list[PricingPlanResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromoCodeListResponse(BaseModel):
    items: list[PromoCodeResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class PromoCodeValidateRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip().upper()


class PromoCodeValidateResponse(BaseModel):
    valid: bool
    promo_code: PromoCodeResponse | None = None
    discount_amount: float | None = None
    final_amount: float | None = None
    message: str | None = None


# ── Admin Billing Dashboard ──────────────────────────────────────────


class AdminBillingSummaryResponse(BaseModel):
    total_teacher_purchases: int = 0
    total_teacher_revenue: int = 0
    total_subscription_revenue: int = 0
    active_discounts: int = 0
    active_promo_codes: int = 0
    total_promo_usage: int = 0
