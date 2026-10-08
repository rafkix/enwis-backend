import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.subscriptions.models import (
    Payment,
    PaymentCard,
    PaymentEvent,
    PaymentStatus,
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
        if sub and sub.expires_at:
            # SQLite doesn't round-trip tzinfo, so a value written as
            # timezone-aware can come back naive. Normalize both sides to
            # naive UTC before comparing so this works on SQLite (dev) and
            # Postgres (prod) alike.
            expires_at = sub.expires_at
            compare_now = now
            if expires_at.tzinfo is None:
                compare_now = now.replace(tzinfo=None)
            elif compare_now.tzinfo is None:
                compare_now = compare_now.replace(tzinfo=UTC)
            if expires_at < compare_now:
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


class PaymentCardRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, card_id: uuid.UUID) -> PaymentCard | None:
        result = await self.db.execute(
            select(PaymentCard).where(PaymentCard.id == card_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, active_only: bool = False) -> list[PaymentCard]:
        q = select(PaymentCard)
        if active_only:
            q = q.where(PaymentCard.is_active.is_(True))
        q = q.order_by(PaymentCard.sort_order, PaymentCard.created_at)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def create(self, data: dict) -> PaymentCard:
        card = PaymentCard(**data)
        self.db.add(card)
        await self.db.flush()
        await self.db.refresh(card)
        return card

    async def update(self, card_id: uuid.UUID, data: dict) -> PaymentCard | None:
        card = await self.get_by_id(card_id)
        if not card:
            return None
        for key, value in data.items():
            if value is not None and hasattr(card, key):
                setattr(card, key, value)
        await self.db.flush()
        await self.db.refresh(card)
        return card

    async def delete(self, card_id: uuid.UUID) -> bool:
        card = await self.get_by_id(card_id)
        if not card:
            return False
        await self.db.delete(card)
        await self.db.flush()
        return True


class PaymentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    _EAGER = (
        selectinload(Payment.plan),
        selectinload(Payment.card),
        selectinload(Payment.events),
    )

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        result = await self.db.execute(
            select(Payment).options(*self._EAGER).where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_ref(self, provider_ref: str) -> Payment | None:
        """Used by gateway webhooks (Payme/Click/...) to find the
        Payment a callback refers to. Unused by the manual-card flow."""
        result = await self.db.execute(
            select(Payment).options(*self._EAGER).where(Payment.provider_ref == provider_ref)
        )
        return result.scalar_one_or_none()

    async def get_owned(self, payment_id: uuid.UUID, user_id: uuid.UUID) -> Payment | None:
        result = await self.db.execute(
            select(Payment)
            .options(*self._EAGER)
            .where(Payment.id == payment_id, Payment.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(self, data: dict) -> Payment:
        payment = Payment(**data)
        self.db.add(payment)
        await self.db.flush()
        await self.db.refresh(payment)
        return payment

    async def list_by_user(
        self, user_id: uuid.UUID, page: int = 1, per_page: int = 20,
    ) -> tuple[list[Payment], int]:
        base = select(Payment).where(Payment.user_id == user_id)
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        q = (
            base.options(*self._EAGER)
            .order_by(Payment.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(q)).scalars().all()
        return list(rows), total

    async def list_admin(
        self,
        status: PaymentStatus | None = None,
        user_id: uuid.UUID | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Payment], int]:
        base = select(Payment)
        if status is not None:
            base = base.where(Payment.status == status)
        if user_id is not None:
            base = base.where(Payment.user_id == user_id)

        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0

        q = (
            base.options(*self._EAGER)
            .order_by(Payment.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(q)).scalars().all()
        return list(rows), total

    async def list_expirable(self, now: datetime) -> list[Payment]:
        """PENDING/WAITING_FOR_REVIEW payments whose deadline has passed."""
        result = await self.db.execute(
            select(Payment).where(
                Payment.status.in_(
                    [PaymentStatus.PENDING, PaymentStatus.WAITING_FOR_REVIEW]
                ),
                Payment.expires_at.is_not(None),
                Payment.expires_at < now,
            )
        )
        return list(result.scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(Payment.status, func.count(Payment.id)).group_by(Payment.status)
            )
        ).all()
        return {row[0].value if hasattr(row[0], "value") else str(row[0]): row[1] for row in rows}

    async def sum_approved_amount(self) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status == PaymentStatus.APPROVED
            )
        )
        return int(result.scalar() or 0)


class PaymentEventRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(
        self,
        payment_id: uuid.UUID,
        to_status: str,
        from_status: str | None = None,
        actor_id: uuid.UUID | None = None,
        note: str | None = None,
    ) -> PaymentEvent:
        event = PaymentEvent(
            payment_id=payment_id,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor_id,
            note=note,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def list_for_payment(self, payment_id: uuid.UUID) -> list[PaymentEvent]:
        result = await self.db.execute(
            select(PaymentEvent)
            .where(PaymentEvent.payment_id == payment_id)
            .order_by(PaymentEvent.created_at)
        )
        return list(result.scalars().all())
