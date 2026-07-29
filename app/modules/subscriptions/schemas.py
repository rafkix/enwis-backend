from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PlanCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    tier: str = Field(..., min_length=1, max_length=20)
    interval: str = "monthly"
    price: int = Field(0, ge=0)
    currency: str = Field("USD", max_length=3)
    max_tests: int = Field(5, ge=-1)
    max_attempts_per_test: int = Field(3, ge=-1)
    max_participants_per_test: int = Field(30, ge=-1)
    ai_generation: bool = False
    advanced_ai: bool = False
    certificate: bool = False
    priority_support: bool = False
    custom_branding: bool = False
    sort_order: int = 0


class PlanUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    price: int | None = Field(None, ge=0)
    max_tests: int | None = Field(None, ge=-1)
    max_attempts_per_test: int | None = Field(None, ge=-1)
    max_participants_per_test: int | None = Field(None, ge=-1)
    ai_generation: bool | None = None
    advanced_ai: bool | None = None
    certificate: bool | None = None
    priority_support: bool | None = None
    custom_branding: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class PlanResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: str | None
    tier: str
    interval: str
    price: int
    currency: str
    max_tests: int
    max_attempts_per_test: int
    max_participants_per_test: int
    ai_generation: bool
    advanced_ai: bool
    certificate: bool
    priority_support: bool
    custom_branding: bool
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubscribeRequest(BaseModel):
    plan_id: UUID
    payment_id: str | None = None


class SubscriptionResponse(BaseModel):
    id: UUID
    user_id: UUID
    plan_id: UUID
    plan_name: str | None = None
    status: str
    starts_at: datetime
    expires_at: datetime | None
    cancelled_at: datetime | None
    tests_used: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CancelSubscriptionRequest(BaseModel):
    reason: str | None = None


class PlanListResponse(BaseModel):
    items: list[PlanResponse]
    total: int


# ─────────────────────────────────────────────────────────────────
# Billing: payment cards (admin-managed receiving cards)
# ─────────────────────────────────────────────────────────────────


class PaymentCardCreate(BaseModel):
    card_number: str = Field(..., min_length=12, max_length=32)
    card_holder_name: str = Field(..., min_length=1, max_length=100)
    bank_name: str | None = Field(None, max_length=100)
    sort_order: int = 0

    @field_validator("card_number")
    @classmethod
    def clean_card_number(cls, v: str) -> str:
        digits = "".join(ch for ch in v if ch.isdigit())
        if not (12 <= len(digits) <= 19):
            raise ValueError("Card number must contain 12-19 digits")
        return digits


class PaymentCardUpdate(BaseModel):
    card_number: str | None = Field(None, min_length=12, max_length=32)
    card_holder_name: str | None = Field(None, min_length=1, max_length=100)
    bank_name: str | None = Field(None, max_length=100)
    is_active: bool | None = None
    sort_order: int | None = None

    @field_validator("card_number")
    @classmethod
    def clean_card_number(cls, v: str | None) -> str | None:
        if v is None:
            return v
        digits = "".join(ch for ch in v if ch.isdigit())
        if not (12 <= len(digits) <= 19):
            raise ValueError("Card number must contain 12-19 digits")
        return digits


class PaymentCardResponse(BaseModel):
    id: UUID
    card_number: str
    card_holder_name: str
    bank_name: str | None
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaymentCardListResponse(BaseModel):
    items: list[PaymentCardResponse]
    total: int


# ─────────────────────────────────────────────────────────────────
# Billing: payments (manual card-transfer purchase flow)
# ─────────────────────────────────────────────────────────────────


class InitiatePaymentRequest(BaseModel):
    plan_id: UUID
    method: str = Field(
        "manual_card",
        description=(
            "Payment method: 'manual_card' (implemented today). "
            "'payme' / 'click' / 'uzcard' are reserved for future gateway integrations."
        ),
    )
    card_id: UUID | None = Field(
        None,
        description=(
            "Which receiving card the user intends to pay to (manual_card only). "
            "If omitted, the first active card is used."
        ),
    )


class PaymentEventResponse(BaseModel):
    id: UUID
    from_status: str | None
    to_status: str
    actor_id: UUID | None
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentResponse(BaseModel):
    id: UUID
    user_id: UUID
    plan_id: UUID
    plan_name: str | None = None
    card_id: UUID | None
    card: PaymentCardResponse | None = None
    subscription_id: UUID | None
    amount: int
    currency: str
    status: str
    method: str = "manual_card"
    receipt_image: bool = False
    receipt_uploaded_at: datetime | None
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    admin_note: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    events: list[PaymentEventResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class RejectPaymentRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ApprovePaymentRequest(BaseModel):
    note: str | None = Field(None, max_length=500)


class BillingCheckoutInfo(BaseModel):
    """What the client needs to render the "pay to this card" screen."""

    payment: PaymentResponse
    cards: list[PaymentCardResponse]
