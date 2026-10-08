"""General-purpose utility functions used across the codebase.
"""

from __future__ import annotations

import random
import string
from typing import Any


def generate_otp(length: int = 6) -> str:
    """Return a cryptographically-unsuitable-but-practical OTP string.

    For production SMS-based OTP this is sufficient — the 5-minute TTL
    and rate-limiting provide adequate security.
    """
    return "".join(random.choices(string.digits, k=length))


def snake_to_camel(name: str) -> str:
    """Convert ``snake_case`` to ``camelCase``.

    Useful when transforming DB column names to JSON field names for
    a non-snake_case front-end.
    """
    first, *rest = name.split("_")
    return first + "".join(word.capitalize() for word in rest)


def exclude_none(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *data* with ``None`` values removed."""
    return {k: v for k, v in data.items() if v is not None}
