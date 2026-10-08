"""Standardized API response envelope.

Every REST endpoint returns data wrapped in this structure so that
frontend consumers can rely on a single shape for success and error
responses.
"""

from __future__ import annotations

import math
from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel):
    """Unified JSON response envelope used by all API endpoints."""

    success: bool = True
    message: str = "OK"
    data: Any = None
    errors: list[str] | None = None

    @classmethod
    def ok(cls, data: Any = None, message: str = "OK") -> APIResponse:
        return cls(success=True, message=message, data=data)

    @classmethod
    def error(
        cls,
        message: str = "Error",
        errors: list[str] | None = None,
    ) -> APIResponse:
        return cls(success=False, message=message, errors=errors)


class PaginatedResponse(BaseModel):
    """Paginated list response envelope."""

    success: bool = True
    message: str = "OK"
    data: list[Any] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 20
    total_pages: int = 1
    has_next: bool = False
    has_previous: bool = False

    @classmethod
    def create(
        cls,
        items: list[Any],
        total: int,
        page: int,
        per_page: int,
    ) -> PaginatedResponse:
        total_pages = max(1, math.ceil(total / per_page)) if total else 1
        return cls(
            success=True,
            message="OK",
            data=items,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        )
