"""Domain exceptions and FastAPI exception handlers.

Every custom exception carries an HTTP status code so the global
exception handler can return a consistent JSON error shape.
"""

from __future__ import annotations

from fastapi import HTTPException, status


class AppError(HTTPException):
    """Base exception for all application-level errors."""

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: str | None = None,
    ) -> None:
        self.message = message
        super().__init__(
            status_code=status_code,
            detail=detail or message,
        )


class NotFoundError(AppError):
    def __init__(self, entity: str = "Resource") -> None:
        super().__init__(
            message=f"{entity} not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ConflictError(AppError):
    def __init__(self, message: str = "Resource already exists") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
        )


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Not authenticated") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ValidationError(AppError):
    def __init__(self, message: str = "Validation failed") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
