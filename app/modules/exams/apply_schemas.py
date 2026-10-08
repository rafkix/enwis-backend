from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ApplyLinkCreate(BaseModel):
    max_uses: int | None = Field(None, ge=1)
    expires_at: datetime | None = None


class ApplyLinkResponse(BaseModel):
    id: UUID
    exam_id: UUID
    code: str
    url: str
    max_uses: int | None
    use_count: int
    expires_at: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplySubmit(BaseModel):
    message: str | None = None


class ApplicantResponse(BaseModel):
    id: UUID
    exam_id: UUID
    user_id: UUID
    user_name: str | None = None
    user_email: str | None = None
    status: str
    message: str | None
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplicantReview(BaseModel):
    status: str = Field(..., pattern=r"^(approved|rejected)$")
