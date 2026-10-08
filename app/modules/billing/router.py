from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_active_user
from app.modules.auth.models import User
from app.modules.billing.schemas import PurchaseTeacherPackageRequest
from app.modules.billing.service import BillingService
from app.modules.users.schemas import ApiResponse

_400 = {400: {"description": "Bad request"}}
_401 = {401: {"description": "Not authenticated"}}
_404 = {404: {"description": "Not found"}}
_422 = {422: {"description": "Validation error"}}

router = APIRouter(prefix="/billing", tags=["Billing"])


def get_billing_service(db: AsyncSession = Depends(get_db)) -> BillingService:
    return BillingService(db)


@router.get(
    "/teacher-package",
    summary="Get teacher package details",
    responses={200: {"description": "Teacher package details"}, **_404},
)
async def get_teacher_package(service: BillingService = Depends(get_billing_service)):
    pkg = await service.get_teacher_package()
    if not pkg:
        return ApiResponse(data={"available": False})
    return ApiResponse(data={
        "available": True,
        "id": str(pkg.id),
        "name": pkg.name,
        "description": pkg.description,
        "price": pkg.price,
        "currency": pkg.currency,
        "is_active": pkg.is_active,
        "created_at": pkg.created_at.isoformat() if pkg.created_at else None,
        "updated_at": pkg.updated_at.isoformat() if pkg.updated_at else None,
    })


@router.post(
    "/teacher-package/purchase",
    summary="Start a teacher package purchase",
    description=(
        "1-qadam: to'lov 'pending' holatda yaratiladi va qaysi kartaga "
        "to'lash kerakligi qaytadi. TEACHER roli BU YERDA berilmaydi — "
        "faqat chek yuklanib (2-qadam), admin tasdiqlagach beriladi."
    ),
    responses={
        200: {"description": "Purchase created — pay to the returned card and upload a receipt."},
        **_400,
        **_401,
    },
)
async def purchase_teacher_package(
    payload: PurchaseTeacherPackageRequest,
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_billing_service),
):
    result = await service.purchase_teacher_package(
        user=user,
        payment_method=payload.payment_method,
        payment_ref=payload.payment_ref,
    )
    return ApiResponse(data=result)


@router.post(
    "/teacher-package/purchases/{purchase_id}/receipt",
    summary="Upload payment receipt for a teacher package purchase",
    responses={200: {"description": "Receipt uploaded, now waiting for admin review."}, **_400, **_404},
)
async def upload_teacher_purchase_receipt(
    purchase_id: str,
    file: UploadFile = File(..., description="To'lov chekining rasmi yoki PDF"),
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_billing_service),
):
    if file.content_type not in {"image/jpeg", "image/png", "image/webp", "application/pdf"}:
        raise HTTPException(400, "File type not allowed. Accepted: jpeg, png, webp, pdf")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "File size must not exceed 5MB")

    import uuid as _uuid

    purchase = await service.upload_teacher_purchase_receipt(
        user, _uuid.UUID(purchase_id), content, file.filename or "receipt.jpg"
    )
    return ApiResponse(data={"id": str(purchase.id), "status": purchase.status})


@router.post(
    "/teacher-package/purchases/{purchase_id}/cancel",
    summary="Cancel a pending teacher package purchase",
    responses={200: {"description": "Purchase cancelled."}, **_400, **_404},
)
async def cancel_teacher_purchase(
    purchase_id: str,
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_billing_service),
):
    import uuid as _uuid

    purchase = await service.cancel_teacher_purchase(user, _uuid.UUID(purchase_id))
    return ApiResponse(data={"id": str(purchase.id), "status": purchase.status})


@router.get(
    "/pricing",
    summary="List pricing plans",
    description="Returns all active pricing plans with their current discounts and limits",
)
async def list_pricing_plans(service: BillingService = Depends(get_billing_service)):
    from app.core.plans import PlanLimits, get_user_plan_tier

    plans = await service.list_pricing_plans(active_only=True)
    result = []
    for plan in plans:
        discount = getattr(plan, "_active_discount", None)
        discount_info = None
        discounted_price = None
        if discount:
            discount_info = {
                "id": str(discount.id),
                "name": discount.name,
                "percentage": discount.percentage,
                "start_date": discount.start_date.isoformat(),
                "end_date": discount.end_date.isoformat(),
                "is_active": discount.is_active,
            }
            discounted_price = service.compute_discounted_price(plan.price, discount.percentage)

        # Plan nomidan tier aniqlaymiz (Bepul->free, Teacher->teacher, Pro->pro, Premium->premium)
        _name_to_tier = {
            "bepul": "free", "free": "free",
            "teacher": "teacher",
            "pro": "pro",
            "premium": "premium",
        }
        tier_key = _name_to_tier.get(plan.name.lower(), "free")
        try:
            tier = get_user_plan_tier(tier_key)
            limits = PlanLimits.get_limits(tier)
        except Exception:
            limits = PlanLimits.get_limits(get_user_plan_tier("free"))

        result.append({
            "id": str(plan.id),
            "name": plan.name,
            "description": plan.description,
            "price": plan.price,
            "currency": plan.currency,
            "interval": plan.interval,
            "is_active": plan.is_active,
            "sort_order": plan.sort_order,
            "is_default": plan.is_default,
            "features": [
                {"id": str(f.id), "feature": f.feature, "sort_order": f.sort_order}
                for f in (plan.features or [])
            ],
            "limits": {
                "max_tests": limits.get("max_tests"),
                "max_participants_per_test": limits.get("max_participants_per_test"),
                "ai_questions_per_month": limits.get("ai_questions_per_month", 0),
                "exam_access": limits.get("exam_access", False),
                "student_management": limits.get("student_management", False),
                "certificate": limits.get("certificate", False),
            },
            "discount": discount_info,
            "discounted_price": discounted_price,
            "created_at": plan.created_at.isoformat(),
            "updated_at": plan.updated_at.isoformat(),
        })
    return {"items": result, "total": len(result)}


@router.post(
    "/promo/validate",
    summary="Validate a promo code",
    responses={200: {"description": "Validation result"}, **_422},
)
async def validate_promo_code(
    payload: dict,
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_billing_service),
):
    from app.modules.billing.schemas import PromoCodeValidateRequest

    req = PromoCodeValidateRequest(**payload)
    result = await service.validate_promo_code(
        code=req.code,
        plan_id=payload.get("plan_id"),
        user_id=user.id,
    )
    return result
