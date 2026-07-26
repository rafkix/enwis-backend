"""Pagination utilities for list endpoints.

Supports cursor-based pagination (recommended for production) and
offset-based pagination (simpler, adequate for admin UIs).
"""

from __future__ import annotations

import math
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationMeta(BaseModel):
    """Metadata embedded in every paginated response."""

    page: int
    per_page: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


def compute_pagination_meta(
    page: int,
    per_page: int,
    total: int,
) -> PaginationMeta:
    """Return a ``PaginationMeta`` from raw query parameters."""
    total_pages = max(1, math.ceil(total / per_page)) if total else 1
    return PaginationMeta(
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
    )


class PaginatedResult[T](BaseModel):
    """A generic container for a page of results."""

    items: list[T]
    pagination: PaginationMeta
