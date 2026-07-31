import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.auth.models import User
from app.modules.billing.schemas import (
    ApproveTeacherPurchaseRequest,
    DiscountCreate,
    DiscountListResponse,
    DiscountResponse,
    DiscountUpdate,
    PricingPlanAdminUpdate,
    PricingPlanListResponse,
    PricingPlanResponse,
    PromoCodeCreate,
    PromoCodeListResponse,
    PromoCodeResponse,
    PromoCodeUpdate,
    RejectTeacherPurchaseRequest,
    TeacherPackageResponse,
    TeacherPackageUpdate,
    TeacherPurchaseListResponse,
    TeacherPurchaseResponse,
)
from app.modules.billing.service import BillingService

require_admin = require_roles("ADMIN")

router = APIRouter(
    tags=["Admin — Billing"],
    dependencies=[Depends(require_admin)],
)


def get_billing_service(db: AsyncSession = Depends(get_db)) -> BillingService:
    return BillingService(db)


# ── Teacher Package (Admin) ──────────────────────────────────────────


@router.get("/teacher-package", response_model=TeacherPackageResponse)
async def admin_get_teacher_package(
    service: BillingService = Depends(get_billing_service),
):
    pkg = await service.get_teacher_package_admin()
    if not pkg:
        pkg = await service.create_default_teacher_package()
    return pkg


@router.put("/teacher-package", response_model=TeacherPackageResponse)
async def admin_update_teacher_package(
    payload: TeacherPackageUpdate,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    return await service.update_teacher_package(payload.model_dump(exclude_none=True))


@router.get("/teacher-purchases", response_model=TeacherPurchaseListResponse)
async def admin_list_teacher_purchases(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: BillingService = Depends(get_billing_service),
):
    rows, total = await service.list_teacher_purchases(page, per_page)
    items = [
        TeacherPurchaseResponse(
            id=p.id,
            user_id=p.user_id,
            package_id=p.package_id,
            card_id=p.card_id,
            amount=p.amount,
            currency=p.currency,
            payment_method=p.payment_method,
            payment_ref=p.payment_ref,
            status=p.status,
            receipt_image=p.receipt_image,
            reviewed_by_id=p.reviewed_by_id,
            reviewed_at=p.reviewed_at,
            rejection_reason=p.rejection_reason,
            purchased_at=p.purchased_at,
        )
        for p in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }


@router.post(
    "/teacher-purchases/{purchase_id}/approve",
    response_model=TeacherPurchaseResponse,
    summary="Approve a teacher package purchase — grants the TEACHER role",
)
async def approve_teacher_purchase(
    purchase_id: uuid.UUID,
    payload: ApproveTeacherPurchaseRequest,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    return await service.approve_teacher_purchase(admin, purchase_id, payload.note)


@router.post(
    "/teacher-purchases/{purchase_id}/reject",
    response_model=TeacherPurchaseResponse,
    summary="Reject a teacher package purchase",
)
async def reject_teacher_purchase(
    purchase_id: uuid.UUID,
    payload: RejectTeacherPurchaseRequest,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    return await service.reject_teacher_purchase(admin, purchase_id, payload.reason)


# ── Pricing Plans (Admin) ────────────────────────────────────────────


@router.get("/pricing", response_model=PricingPlanListResponse)
async def admin_list_pricing_plans(
    service: BillingService = Depends(get_billing_service),
):
    plans = await service.list_pricing_plans(active_only=False)
    items = []
    for plan in plans:
        items.append(PricingPlanResponse(
            id=plan.id,
            name=plan.name,
            description=plan.description,
            price=plan.price,
            currency=plan.currency,
            interval=plan.interval,
            is_active=plan.is_active,
            sort_order=plan.sort_order,
            is_default=plan.is_default,
            features=[
                {
                    "id": str(f.id),
                    "plan_id": str(f.plan_id),
                    "feature": f.feature,
                    "sort_order": f.sort_order,
                    "created_at": f.created_at,
                }
                for f in (plan.features or [])
            ],
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        ))
    return {"items": items, "total": len(items)}


@router.put("/pricing/{plan_id}", response_model=PricingPlanResponse)
async def admin_update_pricing_plan(
    plan_id: uuid.UUID,
    payload: PricingPlanAdminUpdate,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    plan = await service.update_pricing_plan(plan_id, payload.model_dump(exclude_none=True))
    return PricingPlanResponse(
        id=plan.id,
        name=plan.name,
        description=plan.description,
        price=plan.price,
        currency=plan.currency,
        interval=plan.interval,
        is_active=plan.is_active,
        sort_order=plan.sort_order,
        is_default=plan.is_default,
        features=[
            {
                "id": str(f.id),
                "plan_id": str(f.plan_id),
                "feature": f.feature,
                "sort_order": f.sort_order,
                "created_at": f.created_at,
            }
            for f in (plan.features or [])
        ],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


# ── Discounts (Admin) ────────────────────────────────────────────────


@router.post("/discounts", response_model=DiscountResponse, status_code=201)
async def admin_create_discount(
    payload: DiscountCreate,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    return await service.create_discount(payload.model_dump())


@router.put("/discounts/{discount_id}", response_model=DiscountResponse)
async def admin_update_discount(
    discount_id: uuid.UUID,
    payload: DiscountUpdate,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    return await service.update_discount(discount_id, payload.model_dump(exclude_none=True))


@router.delete("/discounts/{discount_id}", status_code=204)
async def admin_delete_discount(
    discount_id: uuid.UUID,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    await service.delete_discount(discount_id)


@router.get("/discounts", response_model=DiscountListResponse)
async def admin_list_discounts(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    active_only: bool = Query(False),
    service: BillingService = Depends(get_billing_service),
):
    rows, total = await service.list_discounts(page, per_page, active_only)
    items = [
        DiscountResponse(
            id=d.id,
            plan_id=d.plan_id,
            name=d.name,
            percentage=d.percentage,
            start_date=d.start_date,
            end_date=d.end_date,
            is_active=d.is_active,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }


# ── Promo Codes (Admin) ──────────────────────────────────────────────


@router.post("/promo-codes", response_model=PromoCodeResponse, status_code=201)
async def admin_create_promo_code(
    payload: PromoCodeCreate,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    return await service.create_promo_code(payload.model_dump())


@router.put("/promo-codes/{code_id}", response_model=PromoCodeResponse)
async def admin_update_promo_code(
    code_id: uuid.UUID,
    payload: PromoCodeUpdate,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    return await service.update_promo_code(code_id, payload.model_dump(exclude_none=True))


@router.delete("/promo-codes/{code_id}", status_code=204)
async def admin_delete_promo_code(
    code_id: uuid.UUID,
    admin: User = Depends(require_admin),
    service: BillingService = Depends(get_billing_service),
):
    await service.delete_promo_code(code_id)


@router.get("/promo-codes", response_model=PromoCodeListResponse)
async def admin_list_promo_codes(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: BillingService = Depends(get_billing_service),
):
    rows, total = await service.list_promo_codes(page, per_page)
    items = []
    for p in rows:
        items.append(PromoCodeResponse(
            id=p.id,
            code=p.code,
            discount_type=p.discount_type.value if hasattr(p.discount_type, "value") else p.discount_type,
            discount_value=p.discount_value,
            usage_limit=p.usage_limit,
            used_count=p.used_count,
            per_user_limit=p.per_user_limit,
            is_active=p.is_active,
            valid_from=p.valid_from,
            valid_until=p.valid_until,
            minimum_amount=p.minimum_amount,
            plans=[{
                "id": str(pl.id),
                "name": pl.name,
                "description": pl.description,
                "price": pl.price,
                "currency": pl.currency,
                "interval": pl.interval,
                "is_active": pl.is_active,
                "sort_order": pl.sort_order,
                "is_default": pl.is_default,
                "features": [
                    {"id": str(f.id), "plan_id": str(f.plan_id), "feature": f.feature, "sort_order": f.sort_order, "created_at": f.created_at}
                    for f in (pl.features or [])
                ],
                "created_at": pl.created_at,
                "updated_at": pl.updated_at,
            } for pl in (p.plans or [])],
            created_at=p.created_at,
            updated_at=p.updated_at,
        ))
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }
