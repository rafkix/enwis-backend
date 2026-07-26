import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.subscriptions.models import (
    Plan,
    SubscriptionStatus,
    UserSubscription,
)


class PlanRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, plan_id: uuid.UUID) -> Plan | None:
        result = await self.db.execute(
            select(Plan).where(Plan.id == plan_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Plan | None:
        result = await self.db.execute(
            select(Plan).where(Plan.name == name)
        )
        return result.scalar_one_or_none()

    async def list_all(self, active_only: bool = False) -> list[Plan]:
        q = select(Plan)
        if active_only:
            q = q.where(Plan.is_active.is_(True))
        q = q.order_by(Plan.sort_order, Plan.price)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def create(self, data: dict) -> Plan:
        plan = Plan(**data)
        self.db.add(plan)
        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    async def update(self, plan_id: uuid.UUID, data: dict) -> Plan | None:
        plan = await self.get_by_id(plan_id)
        if not plan:
            return None
        for key, value in data.items():
            if value is not None and hasattr(plan, key):
                setattr(plan, key, value)
        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    async def delete(self, plan_id: uuid.UUID) -> bool:
        plan = await self.get_by_id(plan_id)
        if not plan:
            return False
        await self.db.delete(plan)
        await self.db.flush()
        return True


class SubscriptionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active_by_user(self, user_id: uuid.UUID) -> UserSubscription | None:
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.plan))
            .where(
                UserSubscription.user_id == user_id,
                UserSubscription.status == SubscriptionStatus.ACTIVE,
            )
            .order_by(UserSubscription.created_at.desc())
        )
        sub = result.scalar_one_or_none()
        if sub and sub.expires_at and sub.expires_at < now:
            sub.status = SubscriptionStatus.EXPIRED
            await self.db.flush()
            return None
        return sub

    async def get_by_id(self, sub_id: uuid.UUID) -> UserSubscription | None:
        result = await self.db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.plan))
            .where(UserSubscription.id == sub_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID) -> list[UserSubscription]:
        result = await self.db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.plan))
            .where(UserSubscription.user_id == user_id)
            .order_by(UserSubscription.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self, user_id: uuid.UUID, plan_id: uuid.UUID,
        starts_at: datetime, expires_at: datetime | None = None,
        payment_id: str | None = None,
    ) -> UserSubscription:
        sub = UserSubscription(
            user_id=user_id,
            plan_id=plan_id,
            status=SubscriptionStatus.ACTIVE,
            starts_at=starts_at,
            expires_at=expires_at,
            payment_id=payment_id,
        )
        self.db.add(sub)
        await self.db.flush()
        await self.db.refresh(sub)
        return sub

    async def cancel(self, sub_id: uuid.UUID) -> UserSubscription | None:
        sub = await self.get_by_id(sub_id)
        if not sub:
            return None
        sub.status = SubscriptionStatus.CANCELLED
        sub.cancelled_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(sub)
        return sub

    async def increment_tests_used(self, sub_id: uuid.UUID) -> None:
        sub = await self.get_by_id(sub_id)
        if sub:
            sub.tests_used += 1
            await self.db.flush()

    async def count_active_by_user(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(UserSubscription.id)).where(
                UserSubscription.user_id == user_id,
                UserSubscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        return result.scalar_one() or 0
