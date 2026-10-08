"""Soft-delete mixin for SQLAlchemy models.

Models that mix in ``SoftDeleteMixin`` gain a ``deleted_at`` column.
Rows are never physically deleted; instead ``deleted_at`` is set to the
current timestamp.  Query helpers filter out soft-deleted rows by default.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class SoftDeleteMixin:
    """Adds a ``deleted_at`` column and convenience methods."""

    __abstract__ = True

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this row as deleted."""
        self.deleted_at = datetime.now(UTC)

    def restore(self) -> None:
        """Un-mark a previously soft-deleted row."""
        self.deleted_at = None
