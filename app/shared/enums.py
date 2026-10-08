"""Application-wide enumerations.

Enums that are shared across modules live here. Module-specific enums
should remain defined inside that module's ``models.py``.
"""

from __future__ import annotations

import enum


class Environment(enum.StrEnum):
    """Runtime environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class SortOrder(enum.StrEnum):
    """Sort direction for paginated queries."""

    ASC = "asc"
    DESC = "desc"
