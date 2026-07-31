from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.admin.models import AdminAction, AdminAuditLog
from app.modules.admin.schemas import (
    AdminContentSummary,
    AdminDashboardResponse,
    AdminPaymentSummary,
    AdminSubscriptionSummary,
    AdminTeacherPurchaseSummary,
    AdminUserSummary,
)
from app.modules.auth.models import Role, User, UserStatus
from app.modules.billing.service import BillingService as TeacherPackageBillingService
from app.modules.exams.models import Certificate, Exam, ExamAttempt
from app.modules.notifications.models import NotificationPriority, NotificationType
from app.modules.notifications.service import NotificationService
from app.modules.questions.models import Question
from app.modules.subscriptions.models import (
    Payment,
    PaymentCard,
    PaymentStatus,
    SubscriptionStatus,
    UserSubscription,
)
from app.modules.subscriptions.repository import (
    PaymentCardRepository,
    PaymentEventRepository,
    PaymentRepository,
    PlanRepository,
)
from app.modules.subscriptions.service import BillingService, SubscriptionService
from app.modules.tests.models import Test

logger = logging.getLogger(__name__)


class AdminAuditLogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(
        self,
        admin_id: uuid.UUID | None,
        action: str,
        target_type: str,
        target_id: str | None,
        detail: str | None = None,
        ip_address: str | None = None,
    ) -> AdminAuditLog:
        log = AdminAuditLog(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip_address=ip_address,
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def list_all(
        self,
        page: int = 1,
        per_page: int = 50,
        action: str | None = None,
        target_type: str | None = None,
    ) -> tuple[list[AdminAuditLog], int]:
        base = select(AdminAuditLog)
        if action:
            base = base.where(AdminAuditLog.action == action)
        if target_type:
            base = base.where(AdminAuditLog.target_type == target_type)

        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0

        q = (
            base.order_by(AdminAuditLog.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(q)).scalars().all()
        return list(rows), total


class AdminService:
    """Administrative operations: dashboard stats, user management,
    payment moderation, plan/card management, and the audit log.

    Every mutating method here requires the caller (the router layer)
    to have already verified the acting user has the ADMIN role — this
    service does not re-check permissions itself, it assumes it's only
    ever invoked from admin-protected routes.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.plan_repo = PlanRepository(db)
        self.card_repo = PaymentCardRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.event_repo = PaymentEventRepository(db)
        self.audit_repo = AdminAuditLogRepository(db)
        self.sub_service = SubscriptionService(db)
        self.billing_service = BillingService(db)
        self.teacher_billing_service = TeacherPackageBillingService(db)
        self.notifications = NotificationService(db)

    # ── Dashboard ───────────────────────────────────────────────

    async def get_dashboard(self) -> AdminDashboardResponse:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        total_users = (await self.db.execute(select(func.count(User.id)))).scalar() or 0
        active_users = (
            await self.db.execute(
                select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
            )
        ).scalar() or 0
        blocked_users = (
            await self.db.execute(
                select(func.count(User.id)).where(User.status == UserStatus.BLOCKED)
            )
        ).scalar() or 0
        pending_users = (
            await self.db.execute(
                select(func.count(User.id)).where(User.status == UserStatus.PENDING)
            )
        ).scalar() or 0
        new_today = (
            await self.db.execute(
                select(func.count(User.id)).where(User.created_at >= today_start)
            )
        ).scalar() or 0
        new_week = (
            await self.db.execute(
                select(func.count(User.id)).where(User.created_at >= week_start)
            )
        ).scalar() or 0

        status_counts = await self.payment_repo.count_by_status()
        total_revenue = await self.payment_repo.sum_approved_amount()

        teacher_status_counts = await self.teacher_billing_service.count_teacher_purchases_by_status()
        teacher_revenue = await self.teacher_billing_service.sum_completed_teacher_amount()
        teacher_pending = teacher_status_counts.get("pending", 0)
        teacher_waiting_for_review = teacher_status_counts.get("waiting_for_review", 0)

        active_subs = (
            await self.db.execute(
                select(func.count(UserSubscription.id)).where(
                    UserSubscription.status == SubscriptionStatus.ACTIVE
                )
            )
        ).scalar() or 0
        tier_rows = (
            await self.db.execute(
                select(User.subscription_tier, func.count(User.id))
                .where(User.subscription_tier.is_not(None))
                .group_by(User.subscription_tier)
            )
        ).all()

        total_tests = (await self.db.execute(select(func.count(Test.id)))).scalar() or 0
        total_questions = (
            await self.db.execute(select(func.count(Question.id)))
        ).scalar() or 0
        total_exams = (await self.db.execute(select(func.count(Exam.id)))).scalar() or 0
        total_attempts = (
            await self.db.execute(select(func.count(ExamAttempt.id)))
        ).scalar() or 0
        total_certificates = (
            await self.db.execute(select(func.count(Certificate.id)))
        ).scalar() or 0

        return AdminDashboardResponse(
            users=AdminUserSummary(
                total=total_users,
                active=active_users,
                blocked=blocked_users,
                pending=pending_users,
                new_today=new_today,
                new_this_week=new_week,
            ),
            payments=AdminPaymentSummary(
                pending=status_counts.get(PaymentStatus.PENDING.value, 0),
                waiting_for_review=status_counts.get(
                    PaymentStatus.WAITING_FOR_REVIEW.value, 0
                ),
                approved=status_counts.get(PaymentStatus.APPROVED.value, 0),
                rejected=status_counts.get(PaymentStatus.REJECTED.value, 0),
                expired=status_counts.get(PaymentStatus.EXPIRED.value, 0),
                cancelled=status_counts.get(PaymentStatus.CANCELLED.value, 0),
                total_revenue=total_revenue,
                combined_pending=status_counts.get(PaymentStatus.PENDING.value, 0)
                + teacher_pending,
                combined_waiting_for_review=status_counts.get(
                    PaymentStatus.WAITING_FOR_REVIEW.value, 0
                )
                + teacher_waiting_for_review,
                combined_revenue=total_revenue + teacher_revenue,
                teacher_purchases=AdminTeacherPurchaseSummary(
                    pending=teacher_pending,
                    waiting_for_review=teacher_waiting_for_review,
                    completed=teacher_status_counts.get("completed", 0),
                    rejected=teacher_status_counts.get("rejected", 0),
                    expired=teacher_status_counts.get("expired", 0),
                    cancelled=teacher_status_counts.get("cancelled", 0),
                    revenue=teacher_revenue,
                ),
            ),
            subscriptions=AdminSubscriptionSummary(
                active=active_subs,
                by_tier={row[0]: row[1] for row in tier_rows},
            ),
            content=AdminContentSummary(
                total_tests=total_tests,
                total_questions=total_questions,
                total_exams=total_exams,
                total_attempts=total_attempts,
                total_certificates=total_certificates,
            ),
        )

    # ── User management ────────────────────────────────────────

    async def list_users(
        self,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
        status: str | None = None,
        role: str | None = None,
    ) -> tuple[list[User], int]:
        base = select(User).options(selectinload(User.roles))
        if search:
            like = f"%{search.strip()}%"
            base = base.where(
                or_(
                    User.username.ilike(like),
                    User.email.ilike(like),
                    User.full_name.ilike(like),
                    User.phone.ilike(like),
                    User.public_id.ilike(like),
                )
            )
        if status:
            base = base.where(User.status == status)
        if role:
            base = base.join(User.roles).where(Role.name == role.upper())

        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0

        q = (
            base.order_by(User.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(q)).unique().scalars().all()
        return list(rows), total

    async def get_user(self, user_id: uuid.UUID) -> User:
        result = await self.db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found")
        return user

    async def update_user_status(
        self, admin: User, user_id: uuid.UUID, new_status: str, reason: str | None,
    ) -> User:
        user = await self.get_user(user_id)
        if user.id == admin.id:
            raise HTTPException(400, "You cannot change your own status")

        old_status = user.status.value if hasattr(user.status, "value") else str(user.status)
        user.status = UserStatus(new_status)
        user.is_active = new_status == "active"

        await self.audit_repo.add(
            admin.id,
            AdminAction.USER_STATUS_CHANGED.value,
            "user",
            str(user.id),
            detail=f"{old_status} -> {new_status}" + (f" ({reason})" if reason else ""),
        )
        try:
            await self.notifications.create(
                user_id=user.id,
                type=NotificationType.SYSTEM,
                title="Account status updated",
                message=f"Your account status changed to '{new_status}'."
                + (f" Reason: {reason}" if reason else ""),
                priority=NotificationPriority.HIGH,
                data={"status": new_status},
            )
        except Exception:
            logger.exception("Failed to notify user of status change")

        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_user_ai_quota(
        self,
        admin: User,
        user_id: uuid.UUID,
        quota_override: int | None,
        reason: str | None,
    ) -> User:
        """Set or clear a per-user override of the tier's monthly AI quota.

        None clears the override (tier default applies again), -1 grants
        unlimited AI questions, and any N >= 0 fixes the monthly quota for
        this user regardless of their subscription tier.
        """
        user = await self.get_user(user_id)
        old_override = user.ai_questions_quota_override
        user.ai_questions_quota_override = quota_override

        detail = f"{old_override} -> {quota_override}" + (f" ({reason})" if reason else "")
        await self.audit_repo.add(
            admin.id,
            AdminAction.USER_AI_QUOTA_CHANGED.value,
            "user",
            str(user.id),
            detail=detail,
        )
        try:
            if quota_override is None:
                message = "Sizning AI savol kvotangiz tarif bo'yicha standart holatga qaytarildi."
            elif quota_override == -1:
                message = "Sizga cheksiz AI savol kvotasi berildi."
            else:
                message = f"Sizning oylik AI savol kvotangiz {quota_override} taga o'zgartirildi."
            await self.notifications.create(
                user_id=user.id,
                type=NotificationType.SYSTEM,
                title="AI quota updated",
                message=message + (f" Sabab: {reason}" if reason else ""),
                priority=NotificationPriority.NORMAL,
                data={"ai_questions_quota_override": quota_override},
            )
        except Exception:
            logger.exception("Failed to notify user of AI quota change")

        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_user_roles(
        self, admin: User, user_id: uuid.UUID, role_names: list[str],
    ) -> User:
        user = await self.get_user(user_id)
        normalized = {r.upper() for r in role_names}

        roles = []
        for name in normalized:
            result = await self.db.execute(select(Role).where(Role.name == name))
            role = result.scalar_one_or_none()
            if not role:
                raise HTTPException(400, f"Unknown role: {name}")
            roles.append(role)

        old_roles = sorted(r.name for r in user.roles)
        user.roles = roles

        await self.audit_repo.add(
            admin.id,
            AdminAction.USER_ROLES_CHANGED.value,
            "user",
            str(user.id),
            detail=f"{old_roles} -> {sorted(normalized)}",
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def delete_user(self, admin: User, user_id: uuid.UUID) -> None:
        user = await self.get_user(user_id)
        if user.id == admin.id:
            raise HTTPException(400, "You cannot delete your own account")

        # Soft delete: keep the row (payment/audit history references it)
        # but deactivate and timestamp it, consistent with the existing
        # `deleted_at` column already on the User model.
        user.deleted_at = datetime.now(UTC)
        user.is_active = False
        user.status = UserStatus.BLOCKED

        await self.audit_repo.add(
            admin.id, AdminAction.USER_DELETED.value, "user", str(user.id),
        )
        await self.db.commit()

    # ── Payment moderation ─────────────────────────────────────

    async def list_payments(
        self,
        status: str | None = None,
        user_id: uuid.UUID | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Payment], int]:
        status_enum = PaymentStatus(status) if status else None
        return await self.payment_repo.list_admin(status_enum, user_id, page, per_page)

    async def get_payment(self, payment_id: uuid.UUID) -> Payment:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise HTTPException(404, "Payment not found")
        return payment

    async def approve_payment(
        self, admin: User, payment_id: uuid.UUID, note: str | None,
    ) -> Payment:
        payment = await self.get_payment(payment_id)
        if payment.status != PaymentStatus.WAITING_FOR_REVIEW:
            raise HTTPException(
                400,
                f"Only payments waiting for review can be approved "
                f"(current status: {payment.status.value})",
            )

        old_status = payment.status.value
        sub = await self.sub_service.activate_or_renew(
            payment.user_id, payment.plan_id, str(payment.id),
        )

        payment.status = PaymentStatus.APPROVED
        payment.reviewed_by_id = admin.id
        payment.reviewed_at = datetime.now(UTC)
        payment.admin_note = note
        payment.subscription_id = sub.id
        payment.expires_at = None

        await self.event_repo.add(
            payment.id, payment.status.value, old_status, admin.id,
            note=note or "Approved",
        )
        await self.audit_repo.add(
            admin.id, AdminAction.PAYMENT_APPROVED.value, "payment", str(payment.id),
            detail=note,
        )
        try:
            await self.notifications.create(
                user_id=payment.user_id,
                type=NotificationType.PAYMENT,
                title="Payment approved",
                message="Your payment was approved and your subscription is now active.",
                priority=NotificationPriority.HIGH,
                data={"payment_id": str(payment.id), "status": "approved"},
            )
        except Exception:
            logger.exception("Failed to notify user of payment approval")

        await self.db.commit()
        return await self.get_payment(payment.id)

    async def reject_payment(
        self, admin: User, payment_id: uuid.UUID, reason: str,
    ) -> Payment:
        payment = await self.get_payment(payment_id)
        if payment.status != PaymentStatus.WAITING_FOR_REVIEW:
            raise HTTPException(
                400,
                f"Only payments waiting for review can be rejected "
                f"(current status: {payment.status.value})",
            )

        old_status = payment.status.value
        payment.status = PaymentStatus.REJECTED
        payment.reviewed_by_id = admin.id
        payment.reviewed_at = datetime.now(UTC)
        payment.rejection_reason = reason
        payment.expires_at = None

        await self.event_repo.add(
            payment.id, payment.status.value, old_status, admin.id, note=reason,
        )
        await self.audit_repo.add(
            admin.id, AdminAction.PAYMENT_REJECTED.value, "payment", str(payment.id),
            detail=reason,
        )
        try:
            await self.notifications.create(
                user_id=payment.user_id,
                type=NotificationType.PAYMENT,
                title="Payment rejected",
                message=f"Your payment receipt was rejected. Reason: {reason}",
                priority=NotificationPriority.HIGH,
                data={"payment_id": str(payment.id), "status": "rejected"},
            )
        except Exception:
            logger.exception("Failed to notify user of payment rejection")

        await self.db.commit()
        return await self.get_payment(payment.id)

    async def get_receipt_file_path(self, payment_id: uuid.UUID) -> str:
        return await self.billing_service.get_receipt_file_path(payment_id, user_id=None)

    # ── Plan management (delegates to SubscriptionService) ─────

    async def create_plan(self, admin: User, data: dict) -> dict:
        plan = await self.sub_service.create_plan(data)
        await self.audit_repo.add(
            admin.id, AdminAction.PLAN_CREATED.value, "plan", str(plan.id), detail=data.get("name"),
        )
        await self.db.commit()
        return plan

    async def update_plan(self, admin: User, plan_id: uuid.UUID, data: dict) -> dict:
        plan = await self.sub_service.update_plan(plan_id, data)
        await self.audit_repo.add(
            admin.id, AdminAction.PLAN_UPDATED.value, "plan", str(plan_id), detail=str(data),
        )
        await self.db.commit()
        return plan

    async def delete_plan(self, admin: User, plan_id: uuid.UUID) -> None:
        await self.sub_service.delete_plan(plan_id)
        await self.audit_repo.add(
            admin.id, AdminAction.PLAN_DELETED.value, "plan", str(plan_id),
        )
        await self.db.commit()

    async def seed_default_plans(self) -> None:
        await self.sub_service.seed_default_plans()

    # ── Payment card management ────────────────────────────────

    async def list_cards(self) -> list[PaymentCard]:
        return await self.card_repo.list_all(active_only=False)

    async def create_card(self, admin: User, data: dict) -> PaymentCard:
        card = await self.card_repo.create(data)
        await self.audit_repo.add(
            admin.id, AdminAction.CARD_CREATED.value, "payment_card", str(card.id),
        )
        await self.db.commit()
        await self.db.refresh(card)
        return card

    async def update_card(
        self, admin: User, card_id: uuid.UUID, data: dict,
    ) -> PaymentCard:
        card = await self.card_repo.update(card_id, data)
        if not card:
            raise HTTPException(404, "Card not found")
        await self.audit_repo.add(
            admin.id, AdminAction.CARD_UPDATED.value, "payment_card", str(card_id),
        )
        await self.db.commit()
        await self.db.refresh(card)
        return card

    async def delete_card(self, admin: User, card_id: uuid.UUID) -> None:
        deleted = await self.card_repo.delete(card_id)
        if not deleted:
            raise HTTPException(404, "Card not found")
        await self.audit_repo.add(
            admin.id, AdminAction.CARD_DELETED.value, "payment_card", str(card_id),
        )
        await self.db.commit()

    # ── Audit logs ──────────────────────────────────────────────

    async def list_audit_logs(
        self, page: int = 1, per_page: int = 50,
        action: str | None = None, target_type: str | None = None,
    ) -> tuple[list[AdminAuditLog], int]:
        return await self.audit_repo.list_all(page, per_page, action, target_type)
