import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.subscriptions.models import SubscriptionStatus
from app.modules.subscriptions.repository import PlanRepository, SubscriptionRepository


class SubscriptionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.plan_repo = PlanRepository(db)
        self.sub_repo = SubscriptionRepository(db)

    async def list_plans(self, active_only: bool = False) -> list[dict]:
        plans = await self.plan_repo.list_all(active_only)
        return [
            {
                "id": p.id,
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "tier": p.tier,
                "interval": p.interval.value if hasattr(p.interval, "value") else p.interval,
                "price": p.price,
                "currency": p.currency,
                "max_tests": p.max_tests,
                "max_attempts_per_test": p.max_attempts_per_test,
                "max_participants_per_test": p.max_participants_per_test,
                "ai_generation": p.ai_generation,
                "advanced_ai": p.advanced_ai,
                "certificate": p.certificate,
                "priority_support": p.priority_support,
                "custom_branding": p.custom_branding,
                "is_active": p.is_active,
                "sort_order": p.sort_order,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in plans
        ]

    async def get_plan(self, plan_id: uuid.UUID) -> dict:
        plan = await self.plan_repo.get_by_id(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")
        return plan

    async def create_plan(self, data: dict) -> dict:
        existing = await self.plan_repo.get_by_name(data["name"])
        if existing:
            raise HTTPException(409, "Plan with this name already exists")
        return await self.plan_repo.create(data)

    async def update_plan(self, plan_id: uuid.UUID, data: dict) -> dict:
        plan = await self.plan_repo.update(plan_id, data)
        if not plan:
            raise HTTPException(404, "Plan not found")
        return plan

    async def delete_plan(self, plan_id: uuid.UUID) -> None:
        deleted = await self.plan_repo.delete(plan_id)
        if not deleted:
            raise HTTPException(404, "Plan not found")

    async def subscribe(
        self, user_id: uuid.UUID, plan_id: uuid.UUID,
        payment_id: str | None = None,
    ) -> dict:
        plan = await self.plan_repo.get_by_id(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")

        existing = await self.sub_repo.get_active_by_user(user_id)
        if existing:
            raise HTTPException(400, "You already have an active subscription")

        now = datetime.now(UTC)
        if plan.interval.value == "monthly":
            expires_at = now + timedelta(days=30)
        elif plan.interval.value == "yearly":
            expires_at = now + timedelta(days=365)
        else:
            expires_at = None

        sub = await self.sub_repo.create(user_id, plan_id, now, expires_at, payment_id)

        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.subscription_tier = plan.tier
            user.subscription_tier_expires_at = expires_at

        await self.db.commit()
        return {
            "id": sub.id,
            "plan_id": sub.plan_id,
            "status": sub.status.value,
            "starts_at": sub.starts_at,
            "expires_at": sub.expires_at,
        }

    async def cancel_subscription(self, user_id: uuid.UUID, subscription_id: uuid.UUID) -> dict:
        sub = await self.sub_repo.get_by_id(subscription_id)
        if not sub:
            raise HTTPException(404, "Subscription not found")
        if sub.user_id != user_id:
            raise HTTPException(403, "Not authorized")
        if sub.status != SubscriptionStatus.ACTIVE:
            raise HTTPException(400, "Subscription is not active")

        cancelled = await self.sub_repo.cancel(subscription_id)

        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.subscription_tier = "FREE"
            user.subscription_tier_expires_at = None

        await self.db.commit()
        return {
            "id": cancelled.id,
            "status": cancelled.status.value,
            "cancelled_at": cancelled.cancelled_at,
        }

    async def get_user_subscription(self, user_id: uuid.UUID) -> dict | None:
        sub = await self.sub_repo.get_active_by_user(user_id)
        if not sub:
            return None
        return {
            "id": sub.id,
            "plan_id": sub.plan_id,
            "plan_name": sub.plan.display_name if sub.plan else None,
            "status": sub.status.value,
            "starts_at": sub.starts_at,
            "expires_at": sub.expires_at,
            "cancelled_at": sub.cancelled_at,
            "tests_used": sub.tests_used,
            "created_at": sub.created_at,
        }

    async def get_user_subscription_history(self, user_id: uuid.UUID) -> list[dict]:
        subs = await self.sub_repo.list_by_user(user_id)
        return [
            {
                "id": s.id,
                "plan_id": s.plan_id,
                "plan_name": s.plan.display_name if s.plan else None,
                "status": s.status.value,
                "starts_at": s.starts_at,
                "expires_at": s.expires_at,
                "cancelled_at": s.cancelled_at,
                "tests_used": s.tests_used,
                "created_at": s.created_at,
            }
            for s in subs
        ]

    async def check_test_limit(self, user_id: uuid.UUID) -> bool:
        sub = await self.sub_repo.get_active_by_user(user_id)
        if not sub or not sub.plan:
            return True
        if sub.plan.max_tests == -1:
            return True
        return sub.tests_used < sub.plan.max_tests

    async def check_ai_access(self, user_id: uuid.UUID) -> bool:
        sub = await self.sub_repo.get_active_by_user(user_id)
        if not sub or not sub.plan:
            return False
        return sub.plan.ai_generation

    async def check_advanced_ai_access(self, user_id: uuid.UUID) -> bool:
        sub = await self.sub_repo.get_active_by_user(user_id)
        if not sub or not sub.plan:
            return False
        return sub.plan.advanced_ai

    async def seed_default_plans(self) -> None:
        defaults = [
            {
                "name": "free",
                "display_name": "Free",
                "description": "For personal use and trying the platform",
                "tier": "FREE",
                "interval": "monthly",
                "price": 0,
                "max_tests": 5,
                "max_attempts_per_test": 3,
                "max_participants_per_test": 30,
                "ai_generation": False,
                "advanced_ai": False,
                "certificate": False,
                "priority_support": False,
                "sort_order": 1,
            },
            {
                "name": "pro",
                "display_name": "Pro",
                "description": "For professional educators and small teams",
                "tier": "PRO",
                "interval": "monthly",
                "price": 29,
                "max_tests": 50,
                "max_attempts_per_test": -1,
                "max_participants_per_test": 300,
                "ai_generation": True,
                "advanced_ai": False,
                "certificate": True,
                "priority_support": True,
                "sort_order": 2,
            },
            {
                "name": "premium",
                "display_name": "Premium",
                "description": "Full-featured plan with advanced AI and priority support",
                "tier": "PREMIUM",
                "interval": "monthly",
                "price": 199,
                "max_tests": -1,
                "max_attempts_per_test": -1,
                "max_participants_per_test": -1,
                "ai_generation": True,
                "advanced_ai": True,
                "certificate": True,
                "priority_support": True,
                "custom_branding": True,
                "sort_order": 3,
            },
        ]
        for d in defaults:
            existing = await self.plan_repo.get_by_name(d["name"])
            if not existing:
                await self.plan_repo.create(d)
        await self.db.commit()
