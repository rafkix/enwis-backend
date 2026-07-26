from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
