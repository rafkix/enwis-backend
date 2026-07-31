"""Onboarding-requirement flags on the user profile.

Google/Telegram signups arrive without a phone or password. We now
require phone verification for them instead of nudging for a
password — these two computed flags on UserResponse drive that:

- requires_phone_verification: True only for social signups with an
  unverified phone.
- requires_password_setup: True only for non-social accounts without
  a password (in practice: never today, since phone registration
  always sets a password — but kept correct for future flows).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User, UserStatus
from app.modules.users.service import UserService


async def _make_user(session: AsyncSession, role_user: Role, **overrides) -> User:
    defaults = dict(
        username="socialuser",
        full_name="Social User",
        status=UserStatus.ACTIVE,
        is_active=True,
        is_verified=True,
    )
    defaults.update(overrides)
    user = User(**defaults)
    user.roles.append(role_user)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_google_signup_requires_phone_not_password(session: AsyncSession, role_user: Role):
    user = await _make_user(
        session, role_user,
        email="g@example.com",
        google_id="g-123",
        is_google_verified=True,
        password_hash=None,
        phone=None,
        phone_verified=False,
    )
    service = UserService(session)
    profile = service._serialize_user(user)

    assert profile.requires_phone_verification is True
    assert profile.requires_password_setup is False


@pytest.mark.asyncio
async def test_telegram_signup_requires_phone_not_password(session: AsyncSession, role_user: Role):
    user = await _make_user(
        session, role_user,
        username="tguser",
        telegram_id="tg-123",
        is_telegram_verified=True,
        password_hash=None,
        phone=None,
        phone_verified=False,
    )
    service = UserService(session)
    profile = service._serialize_user(user)

    assert profile.requires_phone_verification is True
    assert profile.requires_password_setup is False


@pytest.mark.asyncio
async def test_social_user_with_verified_phone_needs_nothing(session: AsyncSession, role_user: Role):
    user = await _make_user(
        session, role_user,
        username="tguser2",
        telegram_id="tg-456",
        is_telegram_verified=True,
        password_hash=None,
        phone="+998901234567",
        phone_verified=True,
    )
    service = UserService(session)
    profile = service._serialize_user(user)

    assert profile.requires_phone_verification is False
    assert profile.requires_password_setup is False


@pytest.mark.asyncio
async def test_phone_registered_user_has_neither_requirement(session: AsyncSession, role_user: Role):
    """Phone-flow registration always sets a password, so this flag stays
    False for that normal signup path."""
    user = await _make_user(
        session, role_user,
        username="phoneuser",
        phone="+998901112233",
        phone_verified=True,
        password_hash="not-a-real-hash",
    )
    service = UserService(session)
    profile = service._serialize_user(user)

    assert profile.requires_phone_verification is False
    assert profile.requires_password_setup is False
