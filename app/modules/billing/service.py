from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import Role, User
from app.modules.billing.models import (
    Discount,
    PricingPlan,
    PricingPlanFeature,
    PromoCode,
    PromoCodeDiscountType,
    PromoCodeUsage,
    TeacherPackage,
    TeacherPurchase,
    promo_code_plans,
)
from app.modules.subscriptions.models import PaymentCard

logger = logging.getLogger(__name__)


class BillingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _now(self) -> datetime:
        return datetime.utcnow()

    # ── Teacher Package ───────────────────────────────────────────────

    async def get_teacher_package(self) -> TeacherPackage | None:
        result = await self.db.execute(
            select(TeacherPackage).where(TeacherPackage.is_active.is_(True)).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_teacher_package_admin(self) -> TeacherPackage | None:
        result = await self.db.execute(select(TeacherPackage).limit(1))
        return result.scalar_one_or_none()

    async def create_default_teacher_package(self) -> TeacherPackage:
        result = await self.db.execute(select(TeacherPackage).limit(1))
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        pkg = TeacherPackage(
            name="Teacher Package",
            description="One-time purchase for lifetime teacher access",
            price=50000,
            currency="UZS",
            is_active=True,
        )
        self.db.add(pkg)
        await self.db.commit()
        await self.db.refresh(pkg)
        return pkg

    async def update_teacher_package(
        self, data: dict
    ) -> TeacherPackage:
        pkg = await self.get_teacher_package_admin()
        if not pkg:
            raise HTTPException(404, "Teacher package not found")
        for key, value in data.items():
            if value is not None and hasattr(pkg, key):
                setattr(pkg, key, value)
        await self.db.commit()
        await self.db.refresh(pkg)
        return pkg

    async def purchase_teacher_package(
        self, user: User, payment_method: str = "manual_card", payment_ref: str | None = None
    ) -> dict:
        """1-qadam: Teacher package uchun to'lov boshlanadi. Bu ENDI
        rolni darhol bermaydi — faqat 'pending' yozuv yaratadi va qaysi
        kartaga to'lash kerakligini qaytaradi. Rol faqat admin chekni
        tasdiqlagach (`approve_teacher_purchase`) beriladi.
        """
        pkg = await self.get_teacher_package()
        if not pkg:
            raise HTTPException(404, "Teacher package not available")
        if not pkg.is_active:
            raise HTTPException(400, "Teacher package is not currently available")

        user_roles = {r.name.upper() for r in (user.roles or [])}
        if "TEACHER" in user_roles:
            raise HTTPException(400, "You are already a teacher")

        # SELF-HEAL: avvalgi (avto-rol davridagi) 'completed' xarid mavjud
        # va foydalanuvchi o'shanda teacher_verified_at olgan, ammo TEACHER
        # roli qandaydir sabab bilan yo'qolgan bo'lsa — qayta to'lov talab
        # qilmasdan rolni tiklaymiz va muvaffaqiyat qaytaramiz.
        completed_result = await self.db.execute(
            select(TeacherPurchase).where(
                TeacherPurchase.user_id == user.id,
                TeacherPurchase.status == "completed",
            ).limit(1)
        )
        completed = completed_result.scalar_one_or_none()
        if completed and user.teacher_verified_at:
            await self._grant_teacher_role(user)
            await self.db.commit()
            return {
                "restored": True,
                "purchase": {
                    "id": str(completed.id),
                    "status": completed.status,
                    "amount": completed.amount,
                    "currency": completed.currency,
                },
                "cards": [],
                "message": "Teacher role restored",
            }

        # Ko'rib chiqilishi kutilayotgan ochiq so'rov bo'lsa, yangisini
        # yaratmaymiz — mavjudini qaytaramiz.
        existing_result = await self.db.execute(
            select(TeacherPurchase).where(
                TeacherPurchase.user_id == user.id,
                TeacherPurchase.status.in_(["pending", "waiting_for_review"]),
            ).limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            return await self._teacher_purchase_checkout_info(existing)

        card_result = await self.db.execute(
            select(PaymentCard)
            .where(PaymentCard.is_active.is_(True))
            .order_by(PaymentCard.sort_order)
            .limit(1)
        )
        card = card_result.scalars().first()

        purchase = TeacherPurchase(
            user_id=user.id,
            package_id=pkg.id,
            card_id=card.id if card else None,
            amount=pkg.price,
            currency=pkg.currency,
            payment_method=payment_method,
            payment_ref=payment_ref,
            status="pending",
        )
        self.db.add(purchase)
        await self.db.commit()
        await self.db.refresh(purchase)

        return await self._teacher_purchase_checkout_info(purchase)

    async def _teacher_purchase_checkout_info(self, purchase: TeacherPurchase) -> dict:
        cards_result = await self.db.execute(
            select(PaymentCard).where(PaymentCard.is_active.is_(True)).order_by(PaymentCard.sort_order)
        )
        cards = cards_result.scalars().all()
        return {
            "purchase": {
                "id": str(purchase.id),
                "status": purchase.status,
                "amount": purchase.amount,
                "currency": purchase.currency,
                "card_id": str(purchase.card_id) if purchase.card_id else None,
            },
            "cards": [
                {
                    "id": str(c.id),
                    "card_number": c.card_number,
                    "card_holder_name": c.card_holder_name,
                    "bank_name": c.bank_name,
                }
                for c in cards
            ],
        }

    async def upload_teacher_purchase_receipt(
        self, user: User, purchase_id: uuid.UUID, file_bytes: bytes, filename: str
    ) -> TeacherPurchase:
        """2-qadam: chek rasmi yuklanadi -> waiting_for_review'ga o'tadi."""
        import os

        purchase = await self._get_own_purchase(user.id, purchase_id)
        if purchase.status != "pending":
            raise HTTPException(
                400, f"Cannot upload a receipt for a purchase in status '{purchase.status}'"
            )

        upload_dir = "static/teacher_purchase_receipts"
        os.makedirs(upload_dir, exist_ok=True)
        ext = (filename or "receipt").rsplit(".", 1)[-1].lower()
        if ext not in {"jpg", "jpeg", "png", "webp", "pdf"}:
            ext = "jpg"
        path = os.path.join(upload_dir, f"{purchase.id}.{ext}")
        with open(path, "wb") as f:
            f.write(file_bytes)

        purchase.receipt_image = True
        purchase.receipt_uploaded_at = datetime.now(UTC)
        purchase.status = "waiting_for_review"
        await self.db.commit()
        await self.db.refresh(purchase)
        return purchase

    async def cancel_teacher_purchase(self, user: User, purchase_id: uuid.UUID) -> TeacherPurchase:
        purchase = await self._get_own_purchase(user.id, purchase_id)
        if purchase.status not in ("pending", "waiting_for_review"):
            raise HTTPException(400, f"Cannot cancel a purchase in status '{purchase.status}'")
        purchase.status = "cancelled"
        await self.db.commit()
        await self.db.refresh(purchase)
        return purchase

    async def _get_own_purchase(self, user_id: uuid.UUID, purchase_id: uuid.UUID) -> TeacherPurchase:
        result = await self.db.execute(
            select(TeacherPurchase).where(
                TeacherPurchase.id == purchase_id, TeacherPurchase.user_id == user_id
            )
        )
        purchase = result.scalar_one_or_none()
        if not purchase:
            raise HTTPException(404, "Purchase not found")
        return purchase

    async def approve_teacher_purchase(
        self, admin: User, purchase_id: uuid.UUID, note: str | None = None
    ) -> TeacherPurchase:
        """Faqat shu yerda — admin tasdiqlagach — TEACHER roli beriladi."""
        result = await self.db.execute(
            select(TeacherPurchase).where(TeacherPurchase.id == purchase_id)
        )
        purchase = result.scalar_one_or_none()
        if not purchase:
            raise HTTPException(404, "Purchase not found")
        if purchase.status != "waiting_for_review":
            raise HTTPException(
                400,
                f"Only purchases waiting for review can be approved "
                f"(current status: {purchase.status})",
            )

        # Guard against approving a purchase whose receipt record is
        # inconsistent with disk (e.g. row says uploaded but the file
        # was lost/never written) — otherwise a role could be granted
        # with no verifiable proof of payment.
        if purchase.receipt_image:
            import os

            found = False
            for ext in ("jpg", "jpeg", "png", "webp", "pdf"):
                if os.path.isfile(
                    os.path.join("static/teacher_purchase_receipts", f"{purchase.id}.{ext}")
                ):
                    found = True
                    break
            if not found:
                raise HTTPException(
                    409,
                    "Receipt file is missing on disk for this purchase — cannot approve "
                    "without verifiable proof of payment. Ask the user to re-upload.",
                )

        user_result = await self.db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == purchase.user_id)
        )
        user = user_result.unique().scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found")

        await self._grant_teacher_role(user)
        purchase.status = "completed"
        purchase.reviewed_by_id = admin.id
        purchase.reviewed_at = datetime.now(UTC)
        purchase.admin_note = note
        await self.db.commit()
        await self.db.refresh(purchase)
        return purchase

    async def reject_teacher_purchase(
        self, admin: User, purchase_id: uuid.UUID, reason: str
    ) -> TeacherPurchase:
        result = await self.db.execute(
            select(TeacherPurchase).where(TeacherPurchase.id == purchase_id)
        )
        purchase = result.scalar_one_or_none()
        if not purchase:
            raise HTTPException(404, "Purchase not found")
        if purchase.status != "waiting_for_review":
            raise HTTPException(
                400,
                f"Only purchases waiting for review can be rejected "
                f"(current status: {purchase.status})",
            )

        purchase.status = "rejected"
        purchase.reviewed_by_id = admin.id
        purchase.reviewed_at = datetime.now(UTC)
        purchase.rejection_reason = reason
        await self.db.commit()
        await self.db.refresh(purchase)
        return purchase

    async def _grant_teacher_role(self, user: User) -> None:
        result = await self.db.execute(select(Role).where(Role.name == "TEACHER"))
        teacher_role = result.scalar_one_or_none()
        if not teacher_role:
            teacher_role = Role(name="TEACHER", description="Teacher role")
            self.db.add(teacher_role)
            await self.db.flush()

        if teacher_role not in user.roles:
            user.roles.append(teacher_role)
        user.teacher_verified_at = self._now()

        # subscription_tier ham TEACHER ga o'tkaziladi.
        # Bu lifetime — expires_at NULL (hech qachon tugamaydi).
        if user.subscription_tier in ("FREE", "free"):
            user.subscription_tier = "TEACHER"
            user.subscription_tier_expires_at = None

    async def has_teacher_access(self, user: User) -> bool:
        """Check if user has teacher role via purchase or admin grant."""
        user_roles = {r.name.upper() for r in (user.roles or [])}
        if "TEACHER" in user_roles or "ADMIN" in user_roles:
            return True
        return False

    async def list_teacher_purchases(
        self, page: int = 1, per_page: int = 20
    ) -> tuple[list[TeacherPurchase], int]:
        base = (
            select(TeacherPurchase)
            .options(selectinload(TeacherPurchase.user), selectinload(TeacherPurchase.package))
        )
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        q = (
            base.order_by(TeacherPurchase.purchased_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(q)).scalars().all()
        return list(rows), total

    async def count_teacher_purchases_by_status(self) -> dict[str, int]:
        """Status breakdown for admin dashboards — mirrors
        PaymentRepository.count_by_status() for the general Payment
        flow, so Teacher Package purchases (a separate table) don't
        silently disappear from admin visibility."""
        rows = (
            await self.db.execute(
                select(TeacherPurchase.status, func.count(TeacherPurchase.id)).group_by(
                    TeacherPurchase.status
                )
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    async def sum_completed_teacher_amount(self) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.sum(TeacherPurchase.amount), 0)).where(
                TeacherPurchase.status == "completed"
            )
        )
        return int(result.scalar() or 0)

    # ── Pricing Plans ─────────────────────────────────────────────────

    async def list_pricing_plans(self, active_only: bool = True) -> list[PricingPlan]:
        base = select(PricingPlan).options(selectinload(PricingPlan.features))
        if active_only:
            base = base.where(PricingPlan.is_active.is_(True))
        base = base.order_by(PricingPlan.sort_order)
        result = await self.db.execute(base)
        plans = result.scalars().all()

        # Attach active discount to each plan
        now = self._now()
        for plan in plans:
            discount_result = await self.db.execute(
                select(Discount).where(
                    Discount.plan_id == plan.id,
                    Discount.is_active.is_(True),
                    Discount.start_date <= now,
                    Discount.end_date >= now,
                ).limit(1)
            )
            plan._active_discount = discount_result.scalar_one_or_none()

        return list(plans)

    async def get_pricing_plan(self, plan_id: uuid.UUID) -> PricingPlan:
        result = await self.db.execute(
            select(PricingPlan)
            .options(selectinload(PricingPlan.features))
            .where(PricingPlan.id == plan_id)
        )
        plan = result.scalar_one_or_none()
        if not plan:
            raise HTTPException(404, "Pricing plan not found")
        return plan

    async def update_pricing_plan(self, plan_id: uuid.UUID, data: dict) -> PricingPlan:
        plan = await self.get_pricing_plan(plan_id)

        features_data = data.pop("features", None)

        for key, value in data.items():
            if value is not None and hasattr(plan, key):
                setattr(plan, key, value)

        if features_data is not None:
            # Remove existing features and replace
            existing_features = await self.db.execute(
                select(PricingPlanFeature).where(PricingPlanFeature.plan_id == plan.id)
            )
            for f in existing_features.scalars().all():
                await self.db.delete(f)

            for f_data in features_data:
                feature = PricingPlanFeature(
                    plan_id=plan.id,
                    feature=f_data.get("feature", ""),
                    sort_order=f_data.get("sort_order", 0),
                )
                self.db.add(feature)

        await self.db.commit()
        await self.db.refresh(plan)
        return plan

    async def seed_default_pricing_plans(self) -> None:
        defaults = [
            {
                "name": "Bepul",
                "description": "Sinab ko'rish uchun asosiy kirish.",
                "price": 0,
                "currency": "UZS",
                "interval": "monthly",
                "is_active": True,
                "sort_order": 1,
                "is_default": True,
                "features": [
                    "10 tagacha test yaratish",
                    "Har bir testga 30 tagacha ishtirokchi",
                    "Avtomatik baholash",
                    "Testni havola orqali ulashish",
                    "Community qo'llab-quvvatlash",
                ],
            },
            {
                "name": "Teacher",
                "description": "Bir martalik to'lov — umrbod o'qituvchi kirishi.",
                "price": 0,  # TeacherPackage.price dan olinadi
                "currency": "UZS",
                "interval": "lifetime",
                "is_active": True,
                "sort_order": 2,
                "is_default": False,
                "features": [
                    "10 tagacha test yaratish",
                    "Har bir testga 30 tagacha ishtirokchi",
                    "AI savol generatori (oyiga 10 ta)",
                    "Imtihon (exam) o'tkazish",
                    "O'quvchilarni boshqarish va baholash",
                    "Avtomatik baholash",
                    "Batafsil statistika",
                ],
            },
            {
                "name": "Pro",
                "description": "Professional o'qituvchilar va kichik jamoalar uchun.",
                "price": 99000,
                "currency": "UZS",
                "interval": "monthly",
                "is_active": True,
                "sort_order": 3,
                "is_default": False,
                "features": [
                    "100 tagacha test yaratish",
                    "Har bir testga 500 tagacha ishtirokchi",
                    "AI savol generatori (oyiga 50 ta)",
                    "Savollar banki",
                    "Imtihon (exam) o'tkazish",
                    "O'quvchilarni boshqarish va baholash",
                    "Guruhlarni boshqarish",
                    "Email qo'llab-quvvatlash",
                ],
            },
            {
                "name": "Premium",
                "description": "To'liq imkoniyatlar, kengaytirilgan AI va prioritet yordam.",
                "price": 199000,
                "currency": "UZS",
                "interval": "monthly",
                "is_active": True,
                "sort_order": 4,
                "is_default": False,
                "features": [
                    "Cheksiz test yaratish",
                    "Cheksiz ishtirokchilar",
                    "AI savol generatori (oyiga 100 ta)",
                    "AI natijalar tahlili",
                    "Sertifikat yaratish",
                    "Savollar banki",
                    "Imtihon (exam) o'tkazish",
                    "O'quvchilarni boshqarish va baholash",
                    "Guruhlarni boshqarish",
                    "Prioritet texnik yordam",
                    "Yangi funksiyalarga erta kirish",
                ],
            },
        ]

        for d in defaults:
            features_list = d.pop("features", [])
            existing = await self.db.execute(
                select(PricingPlan).where(PricingPlan.name == d["name"]).limit(1)
            )
            if existing.scalar_one_or_none():
                continue

            plan = PricingPlan(**d)
            self.db.add(plan)
            await self.db.flush()

            for idx, feat_text in enumerate(features_list):
                feature = PricingPlanFeature(
                    plan_id=plan.id,
                    feature=feat_text,
                    sort_order=idx,
                )
                self.db.add(feature)

        await self.db.commit()

    def compute_discounted_price(self, price: int, discount_percentage: float) -> int:
        return int(price * (100.0 - discount_percentage) / 100.0)

    # ── Discount System ───────────────────────────────────────────────

    async def get_active_discount_for_plan(self, plan_id: uuid.UUID) -> Discount | None:
        now = self._now()
        result = await self.db.execute(
            select(Discount).where(
                Discount.plan_id == plan_id,
                Discount.is_active.is_(True),
                Discount.start_date <= now,
                Discount.end_date >= now,
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def create_discount(self, data: dict) -> Discount:
        plan = await self.get_pricing_plan(data["plan_id"])
        discount = Discount(
            plan_id=data["plan_id"],
            name=data["name"],
            percentage=data["percentage"],
            start_date=data["start_date"],
            end_date=data["end_date"],
            is_active=True,
        )
        self.db.add(discount)
        await self.db.commit()
        await self.db.refresh(discount)
        return discount

    async def update_discount(self, discount_id: uuid.UUID, data: dict) -> Discount:
        result = await self.db.execute(select(Discount).where(Discount.id == discount_id))
        discount = result.scalar_one_or_none()
        if not discount:
            raise HTTPException(404, "Discount not found")
        for key, value in data.items():
            if value is not None and hasattr(discount, key):
                setattr(discount, key, value)
        await self.db.commit()
        await self.db.refresh(discount)
        return discount

    async def delete_discount(self, discount_id: uuid.UUID) -> None:
        result = await self.db.execute(select(Discount).where(Discount.id == discount_id))
        discount = result.scalar_one_or_none()
        if not discount:
            raise HTTPException(404, "Discount not found")
        await self.db.delete(discount)
        await self.db.commit()

    async def list_discounts(
        self, page: int = 1, per_page: int = 20, active_only: bool = False
    ) -> tuple[list[Discount], int]:
        base = select(Discount).options(selectinload(Discount.plan))
        if active_only:
            base = base.where(Discount.is_active.is_(True))
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        q = (
            base.order_by(Discount.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(q)).scalars().all()
        return list(rows), total

    # ── Promo Code System ─────────────────────────────────────────────

    async def create_promo_code(self, data: dict) -> PromoCode:
        existing = await self.db.execute(
            select(PromoCode).where(PromoCode.code == data["code"]).limit(1)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Promo code already exists")

        plan_ids = data.pop("plan_ids", [])
        promo = PromoCode(**data)
        self.db.add(promo)
        await self.db.flush()

        for pid in plan_ids:
            plan = await self.get_pricing_plan(pid)
            await self.db.execute(
                promo_code_plans.insert().values(promo_code_id=promo.id, plan_id=plan.id)
            )

        await self.db.commit()
        await self.db.refresh(promo)
        return promo

    async def update_promo_code(self, code_id: uuid.UUID, data: dict) -> PromoCode:
        result = await self.db.execute(
            select(PromoCode).where(PromoCode.id == code_id)
        )
        promo = result.scalar_one_or_none()
        if not promo:
            raise HTTPException(404, "Promo code not found")

        plan_ids = data.pop("plan_ids", None)

        for key, value in data.items():
            if value is not None and hasattr(promo, key):
                setattr(promo, key, value)

        if plan_ids is not None:
            # Remove existing plan links
            await self.db.execute(
                delete(promo_code_plans).where(promo_code_plans.c.promo_code_id == promo.id)
            )

            for pid in plan_ids:
                plan = await self.get_pricing_plan(pid)
                await self.db.execute(
                    promo_code_plans.insert().values(promo_code_id=promo.id, plan_id=plan.id)
                )

        await self.db.commit()
        await self.db.refresh(promo)
        return promo

    async def delete_promo_code(self, code_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(PromoCode).where(PromoCode.id == code_id)
        )
        promo = result.scalar_one_or_none()
        if not promo:
            raise HTTPException(404, "Promo code not found")
        await self.db.delete(promo)
        await self.db.commit()

    async def list_promo_codes(
        self, page: int = 1, per_page: int = 20
    ) -> tuple[list[PromoCode], int]:
        base = select(PromoCode).options(selectinload(PromoCode.plans))
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        q = (
            base.order_by(PromoCode.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(q)).scalars().all()
        return list(rows), total

    async def validate_promo_code(
        self, code: str, plan_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
    ) -> dict:
        result = await self.db.execute(
            select(PromoCode)
            .options(selectinload(PromoCode.plans))
            .where(PromoCode.code == code)
            .limit(1)
        )
        promo = result.scalar_one_or_none()

        if not promo:
            return {"valid": False, "message": "Promo code not found"}

        now = self._now()

        if not promo.is_active:
            return {"valid": False, "message": "Promo code is inactive"}

        if now < promo.valid_from:
            return {"valid": False, "message": "Promo code is not yet valid"}

        if now > promo.valid_until:
            return {"valid": False, "message": "Promo code has expired"}

        if promo.is_usage_exhausted:
            return {"valid": False, "message": "Promo code usage limit exhausted"}

        # Check per-user limit
        if user_id:
            usage_result = await self.db.execute(
                select(func.count(PromoCodeUsage.id)).where(
                    PromoCodeUsage.promo_code_id == promo.id,
                    PromoCodeUsage.user_id == user_id,
                )
            )
            user_usage = usage_result.scalar() or 0
            if user_usage >= promo.per_user_limit:
                return {
                    "valid": False,
                    "message": "You have already used this promo code the maximum number of times",
                }

        # Check if promo applies to the specified plan
        if plan_id:
            plan_ids = {str(p.id) for p in promo.plans}
            if plan_ids and str(plan_id) not in plan_ids:
                return {
                    "valid": False,
                    "message": "Promo code does not apply to this plan",
                }

        return {
            "valid": True,
            "promo_code": promo,
            "message": "Promo code is valid",
        }

    async def apply_promo_code(
        self, code: str, plan_id: uuid.UUID, user_id: uuid.UUID, amount: int
    ) -> dict:
        validation = await self.validate_promo_code(code, plan_id, user_id)
        if not validation["valid"]:
            raise HTTPException(400, validation.get("message", "Invalid promo code"))

        promo = validation["promo_code"]

        if amount < promo.minimum_amount:
            raise HTTPException(
                400,
                f"Minimum order amount is {promo.minimum_amount} to use this promo code",
            )

        # Calculate discount
        if promo.discount_type == PromoCodeDiscountType.PERCENTAGE:
            discount_amount = int(amount * promo.discount_value / 100.0)
        else:
            discount_amount = min(int(promo.discount_value), amount)

        final_amount = amount - discount_amount

        # Record usage
        usage = PromoCodeUsage(promo_code_id=promo.id, user_id=user_id)
        self.db.add(usage)
        promo.used_count = (promo.used_count or 0) + 1
        await self.db.commit()

        return {
            "valid": True,
            "discount_type": promo.discount_type.value,
            "discount_value": promo.discount_value,
            "discount_amount": discount_amount,
            "original_amount": amount,
            "final_amount": final_amount,
            "code": promo.code,
        }
