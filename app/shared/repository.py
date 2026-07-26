"""Abstract base repository providing common CRUD primitives.

Concrete repositories inherit from ``BaseRepository[T]`` and add
domain-specific query methods.  This class is intentionally thin —
it is *not* a generic DAO that covers every possible operation.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository[T]:
    """Minimal repository base.

    Usage::

        class UserRepository(BaseRepository[User]):
            ...
    """

    def __init__(self, model: type[T], session: AsyncSession) -> None:
        self._model = model
        self._session = session
