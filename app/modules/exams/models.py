import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid as UuidType

from app.core.database import Base
from app.modules.exams.apply_models import ExamApplicant, ExamApplyLink


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ExamStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ExamVisibility(enum.StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    ORGANIZATION = "organization"


class Exam(Base):
    """Scheduling wrapper around a Test.

    An Exam references exactly one Test and never stores questions directly.
    Participants solve the questions contained in the linked Test.
    """

    __tablename__ = "exams"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    test_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("tests.id"), index=True
    )

    status: Mapped[ExamStatus] = mapped_column(
        SAEnum(ExamStatus), default=ExamStatus.DRAFT, index=True
    )
    visibility: Mapped[ExamVisibility] = mapped_column(
        SAEnum(ExamVisibility), default=ExamVisibility.PRIVATE
    )

    start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passing_score: Mapped[int] = mapped_column(Integer, default=60)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)

    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id"), index=True
    )

    test = relationship("Test", lazy="selectin")
    attempts: Mapped[list["ExamAttempt"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", lazy="selectin"
    )
    participants: Mapped[list["ExamParticipant"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", lazy="selectin"
    )
    apply_links: Mapped[list["ExamApplyLink"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", lazy="selectin"
    )
    applicants: Mapped[list["ExamApplicant"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", lazy="selectin"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_exams_owner_status", "owner_id", "status"),
    )


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id"), index=True
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    exam: Mapped["Exam"] = relationship(back_populates="attempts")
    answers: Mapped[list["QuestionAnswer"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_exam_attempts_exam_user", "exam_id", "user_id"),
    )


class QuestionAnswer(Base):
    __tablename__ = "question_answers"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("exam_attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("qb_questions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    selected_option_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, nullable=True
    )
    text_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    points_earned: Mapped[int] = mapped_column(Integer, default=0)

    attempt: Mapped["ExamAttempt"] = relationship(back_populates="answers")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ExamParticipant(Base):
    __tablename__ = "exam_participants"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id"), index=True
    )

    exam: Mapped["Exam"] = relationship(back_populates="participants")
    user = relationship("User", lazy="selectin")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    __table_args__ = (
        Index("ix_exam_participants_exam_user", "exam_id", "user_id", unique=True),
    )


class Result(Base):
    __tablename__ = "results"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    attempt_id = mapped_column(
        UuidType, ForeignKey("exam_attempts.id", ondelete="CASCADE"), unique=True, index=True
    )
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    max_score: Mapped[int] = mapped_column(Integer, default=0)
    percentage: Mapped[float] = mapped_column(default=0.0)
    grade: Mapped[str | None] = mapped_column(String(5), nullable=True)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    unanswered_count: Mapped[int] = mapped_column(Integer, default=0)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    graded_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    attempt = relationship("ExamAttempt", backref="result", uselist=False)


class Certificate(Base):
    """Issued after a successful (passed) Attempt, when the linked Test has
    ``certificate_enabled`` set. One Certificate per Attempt.
    """

    __tablename__ = "certificates"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UuidType,
        ForeignKey("exam_attempts.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id"), index=True
    )

    # Short, human-shareable, publicly verifiable code (e.g. ENWIS-8F3K2Q).
    serial_number: Mapped[str] = mapped_column(
        String(50), unique=True, index=True
    )

    recipient_name: Mapped[str] = mapped_column(String(255))
    exam_title: Mapped[str] = mapped_column(String(255))
    score_percentage: Mapped[float] = mapped_column(default=0.0)
    grade: Mapped[str | None] = mapped_column(String(5), nullable=True)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    attempt = relationship("ExamAttempt", backref="certificate", uselist=False)
    exam = relationship("Exam", lazy="selectin")
    user = relationship("User", lazy="selectin")

    __table_args__ = (
        Index("ix_certificates_exam_user", "exam_id", "user_id"),
    )
