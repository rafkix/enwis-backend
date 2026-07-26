from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Role, User
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
    summary="Request teacher role",
    description="Submits a request to become a teacher. Requires Google or Telegram verification.",
    responses={
        200: {"description": "Request submitted successfully."},
        400: {"description": "Already a teacher or other error."},
        403: {"description": "Forbidden — Google or Telegram account not verified."},
        **_base,
    },
)
async def become_teacher(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.is_google_verified and not user.is_telegram_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must verify your Google or Telegram account before becoming a teacher",
        )

    teacher_role = await db.execute(select(Role).where(Role.name == "TEACHER"))
    teacher_role = teacher_role.scalar_one_or_none()

    if not teacher_role:
        teacher_role = Role(name="TEACHER", description="Teacher role")
        db.add(teacher_role)
        await db.flush()

    if any(r.id == teacher_role.id for r in user.roles):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already a teacher",
        )

    user.roles.append(teacher_role)
    user.teacher_verified_at = datetime.now(UTC)
    await db.commit()

    return ApiResponse(message="Successfully became a teacher")
