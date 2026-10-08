import enum
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
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


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ApplicantStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExamApplyLink(Base):
    __tablename__ = "exam_apply_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, default=lambda: secrets.token_urlsafe(24)
    )
    max_uses: Mapped[int | None] = mapped_column(nullable=True)
    use_count: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    exam = relationship("Exam", back_populates="apply_links")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    __table_args__ = (
        Index("ix_exam_apply_links_exam_active", "exam_id", "is_active"),
    )


class ExamApplicant(Base):
    __tablename__ = "exam_applicants"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id"), index=True
    )
    apply_link_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("exam_apply_links.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ApplicantStatus] = mapped_column(
        SAEnum(ApplicantStatus), default=ApplicantStatus.PENDING, index=True
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    exam = relationship("Exam", back_populates="applicants")
    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id], lazy="selectin")
    apply_link = relationship("ExamApplyLink", lazy="selectin")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    __table_args__ = (
        Index("ix_exam_applicants_exam_user", "exam_id", "user_id", unique=True),
        Index("ix_exam_applicants_exam_status", "exam_id", "status"),
    )
