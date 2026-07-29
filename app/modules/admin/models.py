import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid as UuidType

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AdminAction(enum.StrEnum):
    """Every mutating action an admin can take, for the audit trail."""

    USER_STATUS_CHANGED = "user.status_changed"
    USER_ROLES_CHANGED = "user.roles_changed"
    USER_DELETED = "user.deleted"
    PAYMENT_APPROVED = "payment.approved"
    PAYMENT_REJECTED = "payment.rejected"
    PLAN_CREATED = "plan.created"
    PLAN_UPDATED = "plan.updated"
    PLAN_DELETED = "plan.deleted"
    CARD_CREATED = "card.created"
    CARD_UPDATED = "card.updated"
    CARD_DELETED = "card.deleted"


class AdminAuditLog(Base):
    """Immutable record of every admin-panel mutation.

    Written by AdminService alongside the actual mutation, inside the
    same DB transaction, so the audit trail can never silently drift
    from what actually happened.
    """

    __tablename__ = "admin_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(50), index=True)
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    __table_args__ = (
        Index("ix_admin_audit_target", "target_type", "target_id"),
        Index("ix_admin_audit_created", "created_at"),
    )
