from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationBase(BaseModel):
    type: str
    priority: str
    title: str
    message: str
    data: dict[str, Any] = {}


class NotificationCreate(NotificationBase):
    pass


class NotificationResponse(NotificationBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class MarkAllReadResponse(BaseModel):
    updated_count: int


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    page: int
    per_page: int
    total_pages: int
    unread_count: int
