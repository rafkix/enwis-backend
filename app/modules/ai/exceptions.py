from __future__ import annotations

from fastapi import HTTPException, status


class AIProviderNotFoundError(HTTPException):
    def __init__(self, provider: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"AI provider '{provider}' is not supported or not configured.",
        )


class AIProviderNotAvailableError(HTTPException):
    def __init__(self, provider: str) -> None:
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"AI provider '{provider}' is currently unavailable."
                " Please try another provider."
            ),
        )


class AIResponseValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"AI returned an invalid response: {detail}",
        )


class AIGenerationError(HTTPException):
    def __init__(self, detail: str = "Failed to generate questions from AI provider.") -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


class AIRateLimitError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI provider rate limit exceeded. Please try again later.",
        )


class AITimeoutError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI provider request timed out. Please try again.",
        )


class AINoApiKeyError(HTTPException):
    def __init__(self, provider: str) -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"API key for provider '{provider}' is not configured.",
        )
