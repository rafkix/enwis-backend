"""Smoke test confirming the test environment/fixtures are wired correctly.

The original test suite (test_attempts.py, test_questions.py) was
quarantined — see tests/legacy_disabled/ and tests/README.md. This file
exists so `pytest` has at least one real, passing test against the
current schema instead of collecting nothing.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User


@pytest.mark.asyncio
async def test_user_fixture_is_valid(session: AsyncSession, test_user: User):
    assert test_user.id is not None
    assert test_user.phone == "+998901234567"
    assert test_user.is_active is True
