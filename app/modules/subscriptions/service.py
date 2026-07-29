import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.notifications.models import NotificationPriority, NotificationType
from app.modules.notifications.service import NotificationService
from app.modules.subscriptions.constants import (
    ALLOWED_RECEIPT_MIMES,
    MAX_RECEIPT_SIZE,
    RECEIPT_UPLOAD_DIR,
    RECEIPT_UPLOAD_TIMEOUT_MINUTES,
    REVIEW_TIMEOUT_HOURS,
)
from app.modules.subscriptions.models import (
    PAYMENT_ACTIVE_STATUSES,
    Payment,
    PaymentMethod,
    PaymentStatus,
    SubscriptionStatus,
)
from app.modules.subscriptions.providers import get_provider
from app.modules.subscriptions.repository import (
    PaymentCardRepository,
    PaymentEventRepository,
    PaymentRepository,
    PlanRepository,
    SubscriptionRepository,
)

logger = logging.getLogger(__name__)


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

    async def activate_or_renew(
        self,
        user_id: uuid.UUID,
        plan_id: uuid.UUID,
        payment_id: str | None = None,
    ) -> "UserSubscription":  # noqa: F821 - forward ref, imported lazily below

        plan = await self.plan_repo.get_by_id(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")

        now = datetime.now(UTC)
        if plan.interval.value == "monthly":
            expires_at = now + timedelta(days=30)
        elif plan.interval.value == "yearly":
            expires_at = now + timedelta(days=365)
        else:
            expires_at = None

        # Renewing/upgrading supersedes any currently-active subscription
        # instead of blocking, so an approved payment always results in
        # the user having exactly one active subscription.
        existing = await self.sub_repo.get_active_by_user(user_id)
        if existing:
            existing.status = SubscriptionStatus.CANCELLED
            existing.cancelled_at = now
            await self.db.flush()

        sub = await self.sub_repo.create(user_id, plan_id, now, expires_at, payment_id)

        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.subscription_tier = plan.tier
            user.subscription_tier_expires_at = expires_at
        return sub

    async def subscribe(
        self, user_id: uuid.UUID, plan_id: uuid.UUID,
        payment_id: str | None = None,
    ) -> dict:
        """Directly activate a plan without going through the manual
        payment-review flow. Only allowed for free (price == 0) plans —
        anything else must go through BillingService's
        initiate -> upload receipt -> admin review pipeline so there is
        always an auditable Payment/PaymentEvent trail for paid plans.
        """
        plan = await self.plan_repo.get_by_id(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")
        if plan.price > 0 and payment_id is None:
            raise HTTPException(
                400,
                "Paid plans require the billing flow: POST /billing/payments, "
                "upload a receipt, then wait for admin approval.",
            )

        sub = await self.activate_or_renew(user_id, plan_id, payment_id)
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


class BillingService:
    """User-facing manual card-transfer billing flow.

    Select plan -> initiate payment -> upload receipt screenshot ->
    wait for admin review. Approval/rejection themselves live in
    AdminBillingService (app/modules/admin/service.py) since they
    require admin privileges, but both share this module's
    repositories so the Payment/PaymentEvent trail is written from a
    single place.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.plan_repo = PlanRepository(db)
        self.card_repo = PaymentCardRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.event_repo = PaymentEventRepository(db)
        self.sub_service = SubscriptionService(db)
        self.notifications = NotificationService(db)

    def serialize_payment(self, payment: Payment) -> dict:
        return {
            "id": payment.id,
            "user_id": payment.user_id,
            "plan_id": payment.plan_id,
            "plan_name": payment.plan.display_name if payment.plan else None,
            "card_id": payment.card_id,
            "card": payment.card,
            "subscription_id": payment.subscription_id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status.value,
            "method": payment.method,
            "receipt_image": bool(payment.receipt_image),
            "receipt_uploaded_at": payment.receipt_uploaded_at,
            "reviewed_by_id": payment.reviewed_by_id,
            "reviewed_at": payment.reviewed_at,
            "rejection_reason": payment.rejection_reason,
            "admin_note": payment.admin_note,
            "expires_at": payment.expires_at,
            "created_at": payment.created_at,
            "updated_at": payment.updated_at,
            "events": list(payment.events) if payment.events else [],
        }

    async def list_active_cards(self) -> list:
        return await self.card_repo.list_all(active_only=True)

    async def initiate_payment(
        self,
        user_id: uuid.UUID,
        plan_id: uuid.UUID,
        card_id: uuid.UUID | None,
        method: PaymentMethod = PaymentMethod.MANUAL_CARD,
    ) -> dict:
        plan = await self.plan_repo.get_by_id(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")
        if plan.price <= 0:
            raise HTTPException(
                400, "Free plans don't need a payment — call POST /subscriptions/subscribe"
            )

        provider = get_provider(method)
        if not provider.implemented:
            raise HTTPException(
                501,
                f"Payment method '{method.value}' is not integrated yet. "
                "Use 'manual_card' for now.",
            )

        # Block piling up duplicate in-flight payments for the same plan.
        existing_active, _ = await self.payment_repo.list_by_user(user_id, page=1, per_page=50)
        for p in existing_active:
            if p.plan_id == plan_id and p.status in PAYMENT_ACTIVE_STATUSES:
                raise HTTPException(
                    400,
                    "You already have a pending payment for this plan "
                    f"(status: {p.status.value}). Cancel it before starting a new one.",
                )

        now = datetime.now(UTC)
        payment = await self.payment_repo.create(
            {
                "user_id": user_id,
                "plan_id": plan_id,
                "amount": plan.price,
                "currency": plan.currency,
                "status": PaymentStatus.PENDING,
                "method": method.value,
                "expires_at": now + timedelta(minutes=RECEIPT_UPLOAD_TIMEOUT_MINUTES),
            }
        )

        # Let the provider resolve anything it needs (e.g. which card to
        # show); for the manual-card provider this also validates/picks
        # `card_id`. Real gateways would instead return a checkout URL
        # and typically move straight to WAITING_FOR_REVIEW themselves.
        provider_result = await provider.initiate(self.db, payment, plan, card_id=card_id)
        if provider_result.get("card") is not None:
            payment.card_id = provider_result["card"].id

        await self.event_repo.add(
            payment.id, PaymentStatus.PENDING.value, None, user_id,
            note=f"Payment initiated via {method.value}",
        )
        await self.db.commit()

        payment = await self.payment_repo.get_by_id(payment.id)
        return self.serialize_payment(payment)

    async def upload_receipt(
        self, user_id: uuid.UUID, payment_id: uuid.UUID, file: UploadFile,
    ) -> dict:
        payment = await self.payment_repo.get_owned(payment_id, user_id)
        if not payment:
            raise HTTPException(404, "Payment not found")
        if payment.status != PaymentStatus.PENDING:
            raise HTTPException(
                400, f"Cannot upload a receipt for a payment in status '{payment.status.value}'"
            )

        if file.content_type not in ALLOWED_RECEIPT_MIMES:
            raise HTTPException(
                400, "File type not allowed. Accepted: jpeg, png, webp, pdf"
            )
        content = await file.read()
        if len(content) > MAX_RECEIPT_SIZE:
            raise HTTPException(400, "File too large (max 5 MB)")
        if not content:
            raise HTTPException(400, "Empty file")

        os.makedirs(RECEIPT_UPLOAD_DIR, exist_ok=True)
        ext = (file.filename or "receipt").rsplit(".", 1)[-1].lower()
        if ext not in {"jpg", "jpeg", "png", "webp", "pdf"}:
            ext = "bin"
        filename = f"{uuid.uuid4().hex}.{ext}"
        file_path = os.path.join(RECEIPT_UPLOAD_DIR, filename)
        with open(file_path, "wb") as f:
            f.write(content)

        old_status = payment.status.value
        payment.receipt_image = file_path
        payment.receipt_uploaded_at = datetime.now(UTC)
        payment.status = PaymentStatus.WAITING_FOR_REVIEW
        payment.expires_at = datetime.now(UTC) + timedelta(hours=REVIEW_TIMEOUT_HOURS)

        await self.event_repo.add(
            payment.id, payment.status.value, old_status, user_id,
            note="Receipt uploaded, waiting for admin review",
        )
        await self.db.commit()

        payment = await self.payment_repo.get_by_id(payment.id)
        return self.serialize_payment(payment)

    async def cancel_payment(self, user_id: uuid.UUID, payment_id: uuid.UUID) -> dict:
        payment = await self.payment_repo.get_owned(payment_id, user_id)
        if not payment:
            raise HTTPException(404, "Payment not found")
        if payment.status not in PAYMENT_ACTIVE_STATUSES:
            raise HTTPException(
                400, f"Cannot cancel a payment in status '{payment.status.value}'"
            )

        old_status = payment.status.value
        payment.status = PaymentStatus.CANCELLED
        payment.expires_at = None
        await self.event_repo.add(
            payment.id, payment.status.value, old_status, user_id,
            note="Cancelled by user",
        )
        await self.db.commit()

        payment = await self.payment_repo.get_by_id(payment.id)
        return self.serialize_payment(payment)

    async def get_my_payment(self, user_id: uuid.UUID, payment_id: uuid.UUID) -> dict:
        payment = await self.payment_repo.get_owned(payment_id, user_id)
        if not payment:
            raise HTTPException(404, "Payment not found")
        return self.serialize_payment(payment)

    async def list_my_payments(
        self, user_id: uuid.UUID, page: int = 1, per_page: int = 20,
    ) -> dict:
        rows, total = await self.payment_repo.list_by_user(user_id, page, per_page)
        return {
            "items": [self.serialize_payment(p) for p in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page if total else 0,
        }

    async def get_receipt_file_path(
        self, payment_id: uuid.UUID, user_id: uuid.UUID | None = None,
    ) -> str:
        """Resolve the on-disk receipt path for an owner or an admin.

        Pass ``user_id`` to enforce ownership (regular users); pass
        ``None`` to skip the ownership check (admin callers, which must
        have already passed the ADMIN role dependency at the router).
        """
        if user_id is not None:
            payment = await self.payment_repo.get_owned(payment_id, user_id)
        else:
            payment = await self.payment_repo.get_by_id(payment_id)
        if not payment or not payment.receipt_image:
            raise HTTPException(404, "Receipt not found")
        if not os.path.isfile(payment.receipt_image):
            raise HTTPException(404, "Receipt file is missing on disk")
        return payment.receipt_image

    async def sweep_expired_payments(self) -> int:
        """Mark PENDING/WAITING_FOR_REVIEW payments past their deadline as
        EXPIRED. Intended to be called periodically by the background
        task in app.main. Returns the number of payments expired.
        """
        now = datetime.now(UTC)
        expirable = await self.payment_repo.list_expirable(now)
        for payment in expirable:
            old_status = payment.status.value
            payment.status = PaymentStatus.EXPIRED
            await self.event_repo.add(
                payment.id, payment.status.value, old_status, None,
                note="Auto-expired: deadline passed without completion/review",
            )
            try:
                await self.notifications.create(
                    user_id=payment.user_id,
                    type=NotificationType.PAYMENT,
                    title="Payment expired",
                    message="Your pending payment has expired. Please start a new one if you still want to subscribe.",
                    priority=NotificationPriority.NORMAL,
                    data={"payment_id": str(payment.id), "status": "expired"},
                )
            except Exception:
                logger.exception("Failed to send payment-expired notification")
        if expirable:
            await self.db.commit()
        return len(expirable)
