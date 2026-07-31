
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.users.schemas import (
    ApiResponse,
    DeleteAccountSchema,
    PhoneUpdateRequestSchema,
    PhoneUpdateVerifySchema,
    RevokeOthersSchema,
    UpdateAvatarSchema,
    UpdateUserSchema,
    UserSettingsSchema,
)
from app.modules.users.service import UserService

_400 = {400: {"description": "Bad request — invalid input or business rule violation."}}
_401 = {401: {"description": "Not authenticated — Bearer token missing or invalid."}}
_404 = {404: {"description": "Not found — resource does not exist."}}
_422 = {422: {"description": "Validation error — request body is malformed."}}

_base = {**_401, **_422}

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(get_current_user)],
)


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


@router.get(
    "/me",
    response_model=ApiResponse,
    summary="Get current user profile",
    responses={
        200: {"description": "Profile returned successfully."},
        **_401,
    },
)
async def get_me(
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    return ApiResponse(data=service._serialize_user(user).model_dump())


@router.get(
    "/me/account",
    response_model=ApiResponse,
    summary="Get full account summary",
    description="Returns profile, sessions, devices, plan, referral, and settings.",
    responses={
        200: {"description": "Account summary returned successfully."},
        **_401,
    },
)
async def get_account(
    request: Request,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    current_session_id = request.cookies.get("session_id")
    summary = await service.get_account_summary(user, current_session_id)
    return ApiResponse(data=summary)


@router.get(
    "/me/referral",
    response_model=ApiResponse,
    summary="Get referral summary",
    responses={
        200: {"description": "Referral summary returned successfully."},
        **_401,
    },
)
async def get_referral(
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    summary = await service.get_referral_summary(user)
    return ApiResponse(data=summary)


@router.put(
    "/me",
    response_model=ApiResponse,
    summary="Update profile",
    responses={
        200: {"description": "Profile updated successfully."},
        **_400,
        **_base,
    },
)
async def update_profile(
    data: UpdateUserSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.update_profile(user, data)
    return ApiResponse(data=result["user"].model_dump(), message=result["message"])


@router.delete(
    "/me",
    response_model=ApiResponse,
    summary="Delete account",
    responses={
        200: {"description": "Account deleted successfully."},
        **_400,
        **_base,
    },
)
async def delete_account(
    data: DeleteAccountSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.delete_account(user, data.password)
    return ApiResponse(message=result["message"])


@router.patch(
    "/me/avatar/upload",
    response_model=ApiResponse,
    summary="Upload avatar image",
    responses={
        200: {"description": "Avatar uploaded and updated successfully."},
        **_400,
        **_base,
    },
)
async def upload_avatar(
    avatar: UploadFile = File(
        ..., description="Image file (JPEG / PNG / WebP, max 2 MB)"
    ),
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.update_avatar(user, avatar)
    return ApiResponse(data={"avatar": result["avatar"]}, message=result["message"])


@router.patch(
    "/me/avatar/url",
    response_model=ApiResponse,
    summary="Set avatar via CDN URL",
    responses={
        200: {"description": "Avatar URL updated successfully."},
        **_400,
        **_base,
    },
)
async def update_avatar_url(
    data: UpdateAvatarSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.confirm_avatar_url(user, data.avatar_url)
    return ApiResponse(data={"avatar": result["avatar"]}, message=result["message"])


# NOTE: password set/change now lives only at /auth/set-password and
# /auth/change-password (that version also writes an auth audit-log
# entry, which this one didn't — removed duplicate /me/password/* routes).

# NOTE: device listing/revocation now lives only at /users/me/sessions
# (identical logic to /me/devices/* — removed the duplicate route names).


@router.get(
    "/me/sessions",
    response_model=ApiResponse,
    summary="List active sessions",
    responses={
        200: {"description": "Active sessions returned successfully."},
        **_401,
    },
)
async def get_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    current_session_id = request.cookies.get("session_id")
    sessions = await service.get_sessions(user, current_session_id)
    return ApiResponse(data=[s.model_dump() for s in sessions])


@router.delete(
    "/me/sessions/{session_id}",
    response_model=ApiResponse,
    summary="Revoke a session",
    responses={
        200: {"description": "Session revoked successfully."},
        **_401,
        **_404,
    },
)
async def revoke_session(
    session_id: str,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.revoke_device(user, session_id)
    return ApiResponse(message=result["message"])


@router.delete(
    "/me/sessions",
    response_model=ApiResponse,
    summary="Revoke all other sessions",
    description="Revoke all sessions except the current one.",
    responses={
        200: {"description": "All other sessions revoked successfully."},
        **_400,
        **_base,
    },
)
async def revoke_other_sessions(
    data: RevokeOthersSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.revoke_other_devices(user, data.current_session_id)
    return ApiResponse(message=result["message"])


@router.patch(
    "/me/settings",
    response_model=ApiResponse,
    summary="Update user settings",
    description="Update language, timezone, notification preferences, etc.",
    responses={
        200: {"description": "Settings updated successfully."},
        **_base,
    },
)
async def update_settings(
    data: UserSettingsSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.update_settings(user, data)
    return ApiResponse(data={"changed": result["changed"]}, message=result["message"])


@router.post(
    "/me/phone/request",
    response_model=ApiResponse,
    summary="Request phone number change (step 1)",
    responses={
        200: {"description": "SMS verification code sent successfully."},
        **_400,
        **_base,
    },
)
async def request_phone_update(
    data: PhoneUpdateRequestSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.request_phone_update(user, data.phone)
    return ApiResponse(
        data={"expires_in": result.get("expires_in")},
        message=result["message"],
    )


@router.post(
    "/me/phone/verify",
    response_model=ApiResponse,
    summary="Verify phone number change (step 2)",
    responses={
        200: {"description": "Phone number verified and updated successfully."},
        **_400,
        **_base,
    },
)
async def verify_phone_update(
    data: PhoneUpdateVerifySchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.verify_phone_update(user, data.phone, data.code)
    return ApiResponse(data={"phone": result.get("phone")}, message=result["message"])


@router.post(
    "/me/become-teacher",
    response_model=ApiResponse,
    summary="Teacher role info",
    description="Teacher role is now obtained by purchasing the Teacher Package via POST /api/v1/billing/teacher-package/purchase",
    responses={
        400: {"description": "Must purchase teacher package."},
        **_base,
    },
)
async def become_teacher(
    user: User = Depends(get_current_user),
):

    return ApiResponse(
        message="Teacher role is obtained by purchasing the Teacher Package. "
        "Use POST /api/v1/billing/teacher-package/purchase instead.",
        data={"purchase_endpoint": "/api/v1/billing/teacher-package/purchase"},
    )


@router.get(
    "/me/teacher-status",
    response_model=ApiResponse,
    summary="Get teacher status and purchase info",
    responses={200: {"description": "Teacher status returned."}, **_401},
)
async def get_teacher_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.billing.models import TeacherPurchase

    is_teacher = any(r.name.upper() == "TEACHER" for r in (user.roles or []))
    purchase = None
    if is_teacher:
        result = await db.execute(
            select(TeacherPurchase)
            .where(TeacherPurchase.user_id == user.id, TeacherPurchase.status == "completed")
            .order_by(TeacherPurchase.purchased_at.desc())
            .limit(1)
        )
        purchase = result.scalar_one_or_none()

    return ApiResponse(data={
        "is_teacher": is_teacher,
        "teacher_verified_at": user.teacher_verified_at.isoformat() if user.teacher_verified_at else None,
        "purchase": {
            "amount": purchase.amount,
            "currency": purchase.currency,
            "purchased_at": purchase.purchased_at.isoformat(),
        } if purchase else None,
    })


@router.get(
    "/me/purchases",
    response_model=ApiResponse,
    summary="Get purchase history (teacher package)",
    responses={200: {"description": "Purchase history returned."}, **_401},
)
async def get_my_purchases(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.billing.models import TeacherPurchase

    result = await db.execute(
        select(TeacherPurchase)
        .where(TeacherPurchase.user_id == user.id)
        .order_by(TeacherPurchase.purchased_at.desc())
    )
    purchases = result.scalars().all()
    return ApiResponse(data={
        "items": [
            {
                "id": str(p.id),
                "amount": p.amount,
                "currency": p.currency,
                "payment_method": p.payment_method,
                "status": p.status,
                "purchased_at": p.purchased_at.isoformat(),
            }
            for p in purchases
        ]
    })


@router.get(
    "/me/payments",
    response_model=ApiResponse,
    summary="Get payment history (subscription payments)",
    responses={200: {"description": "Payment history returned."}, **_401},
)
async def get_my_payments(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    from app.modules.subscriptions.repository import PaymentRepository

    repo = PaymentRepository(db)
    payments, total = await repo.list_by_user(user.id, page, per_page)
    return ApiResponse(data={
        "items": [
            {
                "id": str(p.id),
                "plan_id": str(p.plan_id) if p.plan_id else None,
                "plan_name": p.plan.display_name if p.plan else None,
                "amount": p.amount,
                "currency": p.currency,
                "status": p.status.value if hasattr(p.status, "value") else p.status,
                "method": p.method,
                "created_at": p.created_at.isoformat(),
                "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
            }
            for p in payments
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@router.get(
    "/me/ai-usage",
    response_model=ApiResponse,
    summary="Get current AI usage and monthly limit",
    description=(
        "Joriy oyda foydalanilgan AI savol soni va oylik limitni qaytaradi. "
        "FREE tier: yo'q (0/0). TEACHER: 10. PRO: 50. PREMIUM: 100."
    ),
    responses={200: {"description": "AI usage stats"}, **_401},
)
async def get_ai_usage(user: User = Depends(get_current_user)):
    from datetime import UTC, datetime

    from app.core.plans import get_ai_monthly_limit, get_user_plan_tier

    tier = get_user_plan_tier(user.subscription_tier)
    override = getattr(user, "ai_questions_quota_override", None)
    monthly_limit = override if override is not None else get_ai_monthly_limit(tier)
    used = getattr(user, "ai_questions_used", 0) or 0
    reset_at = getattr(user, "ai_questions_reset_at", None)

    # Oy tekshiruvi — agar yangi oy boshlangan bo'lsa, used = 0 ko'rsatamiz
    if reset_at is not None:
        now = datetime.now(UTC)
        if reset_at.year != now.year or reset_at.month != now.month:
            used = 0

    return ApiResponse(data={
        "tier": tier.value,
        "ai_questions_used": used,
        "ai_questions_monthly_limit": monthly_limit,
        "ai_questions_remaining": max(0, monthly_limit - used) if monthly_limit != -1 else -1,
        "ai_questions_reset_at": reset_at.isoformat() if reset_at else None,
        "has_ai_access": monthly_limit != 0,
        "is_custom_quota": override is not None,
    })
