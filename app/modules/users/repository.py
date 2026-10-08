"""Users data-access layer.

Re-exports repositories from auth for convenience.
"""

from app.modules.auth.repository import (
    SessionRepository,
    UserRepository,
)

__all__ = ["SessionRepository", "UserRepository"]
