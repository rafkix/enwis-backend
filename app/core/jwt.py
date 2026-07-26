"""JWT utilities — re-exported from app.core.security for convenience.

This module exists for backward-compatibility with code that imports
from ``app.core.jwt``. New code should use ``app.core.security`` directly.
"""

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)

__all__ = ["create_access_token", "create_refresh_token", "decode_token"]
