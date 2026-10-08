"""Shared FastAPI dependencies used across all modules.

These are lightweight callables designed to be injected via
``Depends()`` in router signatures.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query


@dataclass(frozen=True, slots=True)
class PaginationParams:
    """Normalised pagination query parameters."""

    page: int = 1
    per_page: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


def get_pagination(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
) -> PaginationParams:
    """Dependency that extracts pagination params from query string."""
    return PaginationParams(page=page, per_page=per_page)


@dataclass(frozen=True, slots=True)
class SearchParams:
    """Common search / filter parameters."""

    search: str | None = None
    sort_by: str | None = None
    sort_order: str = "desc"


def get_search_params(
    search: str | None = Query(None, description="Search query"),
    sort_by: str | None = Query(None, description="Sort field"),
    sort_order: str = Query("desc", description="Sort direction: asc or desc"),
) -> SearchParams:
    """Dependency that extracts search params from query string."""
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"
    return SearchParams(search=search, sort_by=sort_by, sort_order=sort_order)
