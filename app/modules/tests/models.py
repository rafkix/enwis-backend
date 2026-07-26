import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid as UuidType

from app.core.database import Base

if TYPE_CHECKING:
    from app.modules.questions.models import Question


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Test(Base):
    __tablename__ = "tests"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    test_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, default=False)
    shuffle_answers: Mapped[bool] = mapped_column(Boolean, default=False)
    show_result: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_review: Mapped[bool] = mapped_column(Boolean, default=True)
    negative_marking: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_submit: Mapped[bool] = mapped_column(Boolean, default=True)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id"), index=True
    )

    test_questions: Mapped[list["TestQuestion"]] = relationship(
        back_populates="test", cascade="all, delete-orphan", lazy="selectin"
    )
    settings: Mapped["TestSettings | None"] = relationship(
        back_populates="test", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_tests_owner_status", "owner_id", "status"),
    )


class TestQuestion(Base):
    __tablename__ = "test_questions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    test_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("tests.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("qb_questions.id", ondelete="CASCADE"), index=True
    )
    order: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=1)
    required: Mapped[bool] = mapped_column(Boolean, default=True)

    test: Mapped["Test"] = relationship(back_populates="test_questions")
    question: Mapped["Question"] = relationship(lazy="selectin")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_test_questions_unique", "test_id", "question_id", unique=True),
    )


class TestSettings(Base):
    __tablename__ = "test_settings"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    test_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("tests.id", ondelete="CASCADE"), unique=True, index=True
    )
    negative_marking: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_submit: Mapped[bool] = mapped_column(Boolean, default=True)
    result_visibility: Mapped[str] = mapped_column(String(20), default="immediate")
    certificate_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    test: Mapped["Test"] = relationship(back_populates="settings")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# NOTE: TestParticipant was removed — participants/registration are
# handled exclusively by app.modules.exams (ExamParticipant / apply flow)
# per the product spec: "Registration belongs to the Exam module" and a
# Test must never store Participants directly.


class TestPracticeAttempt(Base):
    """An ungated "just play the Test" attempt — no registration, no
    Exam involved. Powers test.enwis.uz. Exam attempts (registration,
    time windows, leaderboards, certificates) still live entirely in
    app.modules.exams.
    """

    __tablename__ = "test_practice_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    test_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("tests.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="in_progress", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    max_score: Mapped[int] = mapped_column(Integer, default=0)
    percentage: Mapped[float] = mapped_column(default=0.0)
    # Set only when this attempt was started from a group's quiz feed
    # (app.modules.groups). NULL for plain test.enwis.uz practice runs.
    # No FK constraint on purpose — groups is an optional module and this
    # column must not force a hard dependency / import cycle at the DB
    # level; the app layer (groups.service) is responsible for validity.
    group_quiz_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True, index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    answers: Mapped[list["TestPracticeAnswer"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_test_practice_attempts_user_test", "user_id", "test_id"),
    )


class TestPracticeAnswer(Base):
    __tablename__ = "test_practice_answers"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("test_practice_attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("qb_questions.id", ondelete="CASCADE"), index=True
    )
    selected_option_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
    text_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    points_earned: Mapped[int] = mapped_column(Integer, default=0)

    attempt: Mapped["TestPracticeAttempt"] = relationship(back_populates="answers")

    __table_args__ = (
        Index(
            "ix_test_practice_answers_unique", "attempt_id", "question_id", unique=True
        ),
    )


# NOTE: TestAttempt/TestAnswer (the old, since-removed names) used to be
# the *only* way to attempt a Test, before Exam gained its own
# registration-gated attempt flow. That's why this is called
# TestPracticeAttempt now — to stay unambiguous from ExamAttempt.


class TestFavorite(Base):
    """A user's bookmark/favorite of a public Test.

    NOTE: this is a new, additive table only — it does not modify any
    existing table, column, or relationship. It was required because the
    Tests-module refactor spec added POST/DELETE /tests/{id}/favorite,
    and there was previously no storage at all for this feature.
    """

    __tablename__ = "test_favorites"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    test_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("tests.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_test_favorites_unique", "test_id", "user_id", unique=True),
    )
