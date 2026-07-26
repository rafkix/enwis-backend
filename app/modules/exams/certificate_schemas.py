import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CertificateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    attempt_id: uuid.UUID
    exam_id: uuid.UUID
    user_id: uuid.UUID
    serial_number: str
    recipient_name: str
    exam_title: str
    score_percentage: float
    grade: str | None = None
    issued_at: datetime
    revoked_at: datetime | None = None


class CertificateListResponse(BaseModel):
    items: list[CertificateResponse]
    total: int
