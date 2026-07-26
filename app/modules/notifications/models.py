import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid as UuidType

from app.core.database import Base

if TYPE_CHECKING:
    from app.modules.auth.models import User


class NotificationType(enum.StrEnum):
    SYSTEM = "system"
    EXAM = "exam"
    ATTEMPT = "attempt"
    RESULT = "result"
    ANNOUNCEMENT = "announcement"
    REMINDER = "reminder"
    ACHIEVEMENT = "achievement"
    REFERRAL = "referral"
    PAYMENT = "payment"
    PROMOTION = "promotion"


class NotificationPriority(enum.StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType), default=NotificationType.SYSTEM, index=True
    )
    priority: Mapped[NotificationPriority] = mapped_column(
        SAEnum(NotificationPriority), default=NotificationPriority.NORMAL
    )

    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)

    is_read: Mapped[bool] = mapped_column(default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    user: Mapped["User"] = relationship(back_populates="notifications")

    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_read", "user_id", "is_read"),
    )
