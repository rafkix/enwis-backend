import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid as UuidType

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class QuestionType(enum.StrEnum):
    SINGLE_CHOICE = "single_choice"
    SHORT_ANSWER = "short_answer"
    IMAGE = "image"


class DifficultyLevel(enum.StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Visibility(enum.StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    ORGANIZATION = "organization"


class QuestionStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AttachmentType(enum.StrEnum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    PDF = "pdf"
    OTHER = "other"


# ── Many-to-Many: Question <-> Tag ─────────────────────────────────


question_tags = Table(
    "question_tags",
    Base.metadata,
    Column("question_id", UuidType, ForeignKey("qb_questions.id", ondelete="CASCADE"),
           primary_key=True),
    Column("tag_id", UuidType, ForeignKey("qb_tags.id", ondelete="CASCADE"),
           primary_key=True),
)


# ── Models ─────────────────────────────────────────────────────────


class QuestionCategory(Base):
    __tablename__ = "qb_categories"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("qb_categories.id"), nullable=True
    )

    children: Mapped[list["QuestionCategory"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan", lazy="selectin"
    )
    parent: Mapped["QuestionCategory | None"] = relationship(
        back_populates="children", remote_side="QuestionCategory.id", lazy="selectin"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class QuestionTag(Base):
    __tablename__ = "qb_tags"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class QuestionBank(Base):
    __tablename__ = "qb_banks"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UuidType, ForeignKey("users.id"), index=True)
    visibility: Mapped[Visibility] = mapped_column(
        SAEnum(Visibility), default=Visibility.PRIVATE
    )

    questions: Mapped[list["Question"]] = relationship(
        back_populates="question_bank", cascade="all, delete-orphan", lazy="selectin"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Question(Base):
    __tablename__ = "qb_questions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_type: Mapped[QuestionType] = mapped_column(
        SAEnum(QuestionType), default=QuestionType.SINGLE_CHOICE, index=True
    )
    difficulty: Mapped[DifficultyLevel] = mapped_column(
        SAEnum(DifficultyLevel), default=DifficultyLevel.MEDIUM, index=True
    )
    score: Mapped[int] = mapped_column(Integer, default=1)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Rasch (1-parameter IRT) calibration ─────────────────────────
    # irt_b: item difficulty parameter (logit scale). Estimated from
    # real response data via Joint Maximum Likelihood Estimation (see
    # app.modules.questions.rasch). NULL until calibrated at least
    # once — falls back to the categorical `difficulty` enum above
    # for any question that has never been calibrated.
    irt_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    irt_calibrated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    irt_n_responses: Mapped[int] = mapped_column(Integer, default=0)
    visibility: Mapped[Visibility] = mapped_column(
        SAEnum(Visibility), default=Visibility.PRIVATE, index=True
    )
    status: Mapped[QuestionStatus] = mapped_column(
        SAEnum(QuestionStatus), default=QuestionStatus.DRAFT, index=True
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(UuidType, ForeignKey("users.id"), index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("qb_categories.id"), nullable=True, index=True
    )
    question_bank_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("qb_banks.id"), nullable=True, index=True
    )

    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    choices: Mapped[list["Choice"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", lazy="selectin",
        order_by="Choice.order",
    )
    tags: Mapped[list["QuestionTag"]] = relationship(
        secondary=question_tags, lazy="selectin"
    )
    attachments: Mapped[list["QuestionAttachment"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", lazy="selectin"
    )
    category: Mapped["QuestionCategory | None"] = relationship(lazy="selectin")
    question_bank: Mapped["QuestionBank | None"] = relationship(back_populates="questions")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_qb_questions_owner_status", "owner_id", "status"),
        Index("ix_qb_questions_type_diff", "question_type", "difficulty"),
    )


class Choice(Base):
    __tablename__ = "qb_choices"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("qb_questions.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped["Question"] = relationship(back_populates="choices")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class QuestionTypeMeta(Base):
    """Metadata about question types (e.g. has_options, max_options)."""

    __tablename__ = "question_types"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_options: Mapped[bool] = mapped_column(Boolean, default=True)
    has_correct_answer: Mapped[bool] = mapped_column(Boolean, default=True)
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    has_video: Mapped[bool] = mapped_column(Boolean, default=False)
    max_options: Mapped[int] = mapped_column(Integer, default=6)
    min_options: Mapped[int] = mapped_column(Integer, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class QuestionAttachment(Base):
    __tablename__ = "qb_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("qb_questions.id", ondelete="CASCADE"), index=True
    )
    file_type: Mapped[AttachmentType] = mapped_column(
        SAEnum(AttachmentType), default=AttachmentType.IMAGE
    )
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    question: Mapped["Question"] = relationship(back_populates="attachments")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
