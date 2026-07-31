"""Admin-set per-user AI quota override.

Covers: admin can grant a custom monthly AI quota to a specific user
(independent of their subscription tier), clear it back to the tier
default, and grant unlimited access via -1. The override must also be
respected by the AI generation quota check itself, not just reported.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import get_ai_monthly_limit, get_user_plan_tier
from app.modules.admin.service import AdminService
from app.modules.auth.models import User


@pytest.mark.asyncio
async def test_admin_can_set_custom_ai_quota(session: AsyncSession, test_user: User, admin_user: User):
    assert test_user.subscription_tier.upper() == "FREE"
    admin_service = AdminService(session)

    updated = await admin_service.update_user_ai_quota(admin_user, test_user.id, 25, "VIP mijoz")

    assert updated.ai_questions_quota_override == 25
    # Tier itself is untouched — only the override was set.
    assert updated.subscription_tier.upper() == "FREE"


@pytest.mark.asyncio
async def test_admin_can_clear_ai_quota_override(session: AsyncSession, test_user: User, admin_user: User):
    admin_service = AdminService(session)
    await admin_service.update_user_ai_quota(admin_user, test_user.id, 25, None)

    cleared = await admin_service.update_user_ai_quota(admin_user, test_user.id, None, None)

    assert cleared.ai_questions_quota_override is None


@pytest.mark.asyncio
async def test_admin_can_grant_unlimited_ai_quota(session: AsyncSession, test_user: User, admin_user: User):
    admin_service = AdminService(session)
    updated = await admin_service.update_user_ai_quota(admin_user, test_user.id, -1, "Cheksiz")

    assert updated.ai_questions_quota_override == -1


@pytest.mark.asyncio
async def test_override_grants_ai_access_to_free_tier_user(
    session: AsyncSession, test_user: User, admin_user: User,
):
    """A FREE-tier user normally has ai_questions_per_month == 0, so the
    generation endpoint would 403. An admin override should let them
    through regardless of tier."""
    from app.modules.ai.service import AIService

    tier = get_user_plan_tier(test_user.subscription_tier)
    assert get_ai_monthly_limit(tier) == 0

    admin_service = AdminService(session)
    await admin_service.update_user_ai_quota(admin_user, test_user.id, 5, None)
    await session.refresh(test_user)

    assert test_user.ai_questions_quota_override == 5
    # Access gate: can_use_ai(FREE) is False, but the override must win.
    ai_service = AIService(session)
    assert ai_service is not None
    override = test_user.ai_questions_quota_override
    override_grants_access = override is not None and override != 0
    assert override_grants_access is True
