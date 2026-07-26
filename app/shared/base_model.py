"""Shared declarative base and common model mixins.

Every SQLAlchemy model in the application inherits from `BaseModel`
defined here, guaranteeing a consistent primary key strategy and
audit timestamp columns across all modules.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Root declarative base for all ORM models in the application."""


class BaseModel(Base):
    """Abstract base providing a UUID primary key and audit timestamps.

    All domain models across all modules (auth, users, and future
    modules such as organizations, exams, question_bank, attempts,
    payments, notifications) must inherit from this class to ensure
    a consistent schema foundation.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
