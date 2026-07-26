"""Redis connection manager.

Provides an async Redis client configured from application settings.
The client is created lazily on first access and can be closed cleanly
during application shutdown.
"""

from __future__ import annotations

from redis.asyncio import Redis as AsyncRedis  # type: ignore[import-untyped]

from app.core.config import settings

_redis: AsyncRedis | None = None


async def get_redis() -> AsyncRedis:
    """Return the application's async Redis client, creating it lazily."""
    global _redis  # noqa: PLW0603
    if _redis is None:
        _redis = AsyncRedis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """Close the Redis connection pool if it was opened."""
    global _redis  # noqa: PLW0603
    if _redis is not None:
        await _redis.close()
        _redis = None
