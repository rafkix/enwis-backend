"""Shared input validators reusable across all modules.

These are pure functions that raise ``ValueError`` on invalid input.
They are designed to be called from Pydantic ``@field_validator``
decorators or from service-layer validation logic.
"""

from __future__ import annotations

import re
import uuid as uuid_mod

UZBEK_PHONE_PREFIXES = (
    "+998", "998", "90", "91", "93", "94", "95", "97",
    "98", "99", "33", "50", "55", "60", "61", "62",
    "65", "66", "67", "68", "69", "70", "71", "72",
    "77", "78", "79", "88", "99",
)


def validate_phone(value: str) -> str:
    """Validate and normalise a phone number.

    Accepts international format with leading ``+`` or without.
    Normalises to E.164-like format (e.g. ``+998901234567``).
    """
    cleaned = re.sub(r"[\s\-\(\)]", "", value.strip())
    if not re.match(r"^\+?[0-9]{7,15}$", cleaned):
        raise ValueError("Invalid phone number format")
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


def validate_username(value: str) -> str:
    """Validate a username: alphanumeric and underscores only, 3-30 chars."""
    cleaned = value.strip().lower()
    if not re.match(r"^[a-zA-Z0-9_]{3,30}$", cleaned):
        raise ValueError(
            "Username must be 3-30 characters and contain only letters, numbers, and underscores"
        )
    return cleaned


def validate_email(value: str) -> str:
    """Basic email format validation."""
    cleaned = value.strip().lower()
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, cleaned):
        raise ValueError("Invalid email format")
    return cleaned


def validate_password_strength(value: str) -> str:
    """Validate password meets minimum security requirements."""
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters")
    if " " in value:
        raise ValueError("Password must not contain spaces")
    return value


def validate_url(value: str) -> str:
    """Validate that a string is a valid HTTP(S) URL."""
    cleaned = value.strip()
    if not re.match(r"^https?://", cleaned):
        raise ValueError("URL must start with http:// or https://")
    return cleaned


def validate_uuid_string(value: str) -> str:
    """Validate that a string is a valid UUID format."""
    try:
        uuid_mod.UUID(value)
    except ValueError:
        raise ValueError("Invalid UUID format") from None
    return value


def validate_pagination_params(page: int, per_page: int) -> tuple[int, int]:
    """Validate and normalise pagination parameters."""
    page = max(page, 1)
    per_page = min(max(per_page, 20), 100)
    return page, per_page


def validate_sort_field(value: str, allowed_fields: set[str]) -> str:
    """Validate a sort field name against an allowed set."""
    if value.lstrip("-") not in allowed_fields:
        raise ValueError(f"Invalid sort field: {value}")
    return value
