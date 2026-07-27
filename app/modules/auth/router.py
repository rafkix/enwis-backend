from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import clear_auth_cookies, set_auth_cookies
from app.core.database import get_db
from app.core.rate_limit import forgot_password_limiter, login_limiter, sms_limiter
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResetRequest,
    ForgotPasswordSendCodeRequest,
    LinkedAccountResponse,
    LinkGoogleRequest,
    LinkTelegramRequest,
    LoginRequest,
    LogoutResponse,
    MessageResponse,
    RefreshRequest,
    RegisterSendCodeRequest,
    RegisterVerifyRequest,
    ResetPasswordRequest,
    SetPasswordRequest,
    SocialLoginRequest,
    TelegramWebAppAuthRequest,
    TokenResponse,
)
from app.modules.auth.service import AuthService

_400 = {400: {"description": "Bad request — invalid credentials or business rule violation."}}
_401 = {401: {"description": "Not authenticated — Bearer token missing or expired."}}
_422 = {422: {"description": "Validation error — request body is malformed."}}

_base = {**_400, **_422}
_auth = {**_401, **_422}

router = APIRouter(prefix="/auth", tags=["Auth"])


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


@router.post(
    "/register/send-code",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Register — step 1: send SMS code",
    description=(
        "app.enwis.uz uchun BITTA marta bajariladigan ro'yxatdan o'tishning "
        "birinchi qadami. Ism-familiya, telefon va parol shu yerda beriladi; "
        "login (username) alohida so'ralmaydi — u to'liq ismdan avtomatik "
        "generatsiya qilinadi. SMS kodni tasdiqlash uchun "
        "`/auth/register/verify` ni chaqiring."
    ),
    responses={
        200: {"description": "SMS code sent successfully."},
        **_base,
        409: {"description": "Conflict — phone number is already registered."},
    },
)
async def register_send_code(
    payload: RegisterSendCodeRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
    _rl: None = Depends(sms_limiter),
):
    return await service.register_send_code(
        full_name=payload.full_name,
        phone=payload.phone,
        password=payload.password,
        request=request,
    )


@router.post(
    "/register/verify",
    response_model=TokenResponse,
    summary="Register — step 2: verify SMS code",
    description=(
        "SMS kodni tasdiqlaydi va akkauntni yaratadi. Login avtomatik "
        "generatsiya qilingan holda qaytariladi (natijadagi profil "
        "ma'lumotidan ko'rish mumkin). Bu — ro'yxatdan o'tishning oxirgi "
        "qadami, undan keyin foydalanuvchi doim login+parol bilan kiradi."
    ),
    responses={
        200: {"description": "Phone verified, account created. Tokens returned."},
        **_base,
    },
)
async def register_verify(
    payload: RegisterVerifyRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.register_verify(
        phone=payload.phone,
        code=payload.code,
        request=request,
    )
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login (app.enwis.uz)",
    description="app.enwis.uz uchun yagona login yo'li: login (avtomatik generatsiya qilingan) + parol.",
    responses={
        200: {"description": "Login successful. Tokens returned."},
        **_base,
        401: {"description": "Invalid credentials — identifier or password is incorrect."},
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    _rl: None = Depends(login_limiter),
):
    result = await service.login(
        username=payload.username,
        password=payload.password,
        request=request,
    )
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    responses={
        200: {"description": "Tokens refreshed successfully."},
        **_base,
        401: {"description": "Refresh token is invalid or has expired."},
    },
)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    refresh_token = payload.refresh_token or request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token required")
    result = await service.refresh(refresh_token, request)
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


# NOTE: "get current user" now lives only at /users/me (basic profile) and
# /users/me/account (profile + sessions + subscription + settings, which
# is a superset of what this endpoint used to return) — removed duplicate
# /auth/me.


# NOTE: session listing/revocation now lives only at /users/me/sessions
# (removed duplicate /auth/sessions endpoints — same Session table, same logic).


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout",
    responses={
        200: {"description": "Logged out successfully."},
        **_base,
    },
)
async def logout(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    refresh_token = payload.refresh_token or request.cookies.get("refresh_token")
    if not refresh_token:
        clear_auth_cookies(response)
        return {"success": True, "message": "Logged out"}
    result = await service.logout(refresh_token)
    clear_auth_cookies(response)
    return result


@router.post(
    "/logout-all",
    response_model=LogoutResponse,
    summary="Logout from all devices",
    responses={
        200: {"description": "Logged out from all devices successfully."},
        **_auth,
    },
)
async def logout_all(
    response: Response,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    result = await service.logout_all(user)
    clear_auth_cookies(response)
    return result


@router.post(
    "/set-password",
    response_model=MessageResponse,
    summary="Set password (social users)",
    responses={
        200: {"description": "Password set successfully."},
        **_base,
        **_auth,
    },
)
async def set_password(
    payload: SetPasswordRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.set_password(user, payload.new_password)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password",
    responses={
        200: {"description": "Password changed successfully."},
        **_base,
        **_auth,
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
    responses={
        200: {"description": "Reset email sent if the address is registered."},
        **_base,
    },
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service),
    _rl: None = Depends(forgot_password_limiter),
):
    return await service.forgot_password(str(payload.email))


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password via token",
    responses={
        200: {"description": "Password reset successfully."},
        **_base,
        401: {"description": "Reset token is invalid or has expired."},
    },
)
async def reset_password(
    payload: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
    _rl: None = Depends(forgot_password_limiter),
):
    return await service.reset_password(payload.token, payload.new_password)


@router.post(
    "/forgot-password/send-code",
    response_model=MessageResponse,
    summary="Request password reset via phone (app.enwis.uz) — step 1",
    description=(
        "app.enwis.uz uchun: telefon raqami bo'yicha akkaunt topilsa, "
        "SMS orqali 6 xonali kod yuboriladi. Akkaunt mavjudligini oshkor "
        "qilmaslik uchun javob har doim bir xil. `/auth/forgot-password/reset` "
        "bilan davom eting."
    ),
    responses={200: {"description": "Generic success response."}, **_base},
)
async def forgot_password_send_code(
    payload: ForgotPasswordSendCodeRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
    _rl: None = Depends(sms_limiter),
):
    return await service.forgot_password_send_code(payload.phone, request)


@router.post(
    "/forgot-password/reset",
    response_model=MessageResponse,
    summary="Confirm SMS code and set new password (app.enwis.uz) — step 2",
    responses={
        200: {"description": "Password reset successfully."},
        **_base,
        410: {"description": "Code has expired."},
        429: {"description": "Too many attempts."},
    },
)
async def forgot_password_reset(
    payload: ForgotPasswordResetRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
    _rl: None = Depends(forgot_password_limiter),
):
    return await service.forgot_password_reset(
        payload.phone, payload.code, payload.new_password, request
    )


# NOTE: "verify my own phone while logged in" now lives only at
# /users/me/phone/request + /users/me/phone/verify (that version also
# checks the number isn't already used by another account, so it fully
# replaces this — removed duplicate /auth/phone/send-code + /phone/verify).


# NOTE: phone-based registration now lives only at
# /auth/register/send-code + /auth/register/verify above (removed the
# older, parallel /auth/phone/register* pair — same feature, one path).
#
# NOTE: login-by-OTP (/auth/phone/login/send-code + /verify) has been
# removed entirely. app.enwis.uz always logs in with login + password
# (see /auth/login above); test.enwis.uz and exams.enwis.uz use Google
# or Telegram only (see /auth/google, /auth/telegram below) — a phone
# OTP login for app.enwis.uz was a redundant third way in.


@router.post(
    "/google",
    response_model=TokenResponse,
    summary="Login with Google (test.enwis.uz / exams.enwis.uz)",
    description=(
        "test.enwis.uz va exams.enwis.uz uchun yagona login yo'li. Bir "
        "chaqiriqning o'zida ham ro'yxatdan o'tkazadi (agar akkaunt "
        "mavjud bo'lmasa), ham login qiladi (agar mavjud bo'lsa) — "
        "alohida 'register' bosqichi shart emas."
    ),
    responses={
        200: {"description": "Google authentication successful. Tokens returned."},
        **_base,
    },
)
async def google_auth(
    payload: SocialLoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.google_auth(payload.id_token, request)
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


@router.post(
    "/telegram",
    response_model=TokenResponse,
    summary="Login with Telegram (test.enwis.uz / exams.enwis.uz)",
    description=(
        "test.enwis.uz va exams.enwis.uz uchun Telegram orqali login/"
        "register — bir chaqiriqda ikkalasi ham."
    ),
    responses={
        200: {"description": "Telegram authentication successful. Tokens returned."},
        **_base,
    },
)
async def telegram_auth(
    payload: SocialLoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.telegram_auth(payload.telegram_data, request)
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


@router.post(
    "/telegram/webapp",
    response_model=TokenResponse,
    summary="Login with Telegram Mini App initData (web3.enwis.uz ONLY)",
    description=(
        "web3.enwis.uz — Telegram Mini App ichida ochilganda ishlatiladigan "
        "YAGONA auth yo'li. `Telegram.WebApp.initData`ni xom holida "
        "yuboring — bu boshqa `/auth/telegram` (login-widget) dan farqli "
        "tekshirish (HMAC secret derivation) ishlatadi."
    ),
    responses={
        200: {"description": "Telegram Mini App authentication successful. Tokens returned."},
        **_base,
        401: {"description": "initData signature invalid or expired."},
    },
)
async def telegram_webapp_auth(
    payload: TelegramWebAppAuthRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.telegram_webapp_auth(payload.init_data, request)
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


@router.post(
    "/google/link",
    response_model=LinkedAccountResponse,
    summary="Link a Google account",
    responses={
        200: {"description": "Google account linked successfully."},
        **_auth,
        409: {"description": "Conflict — this Google account is already linked to another user."},
    },
)
async def link_google(
    payload: LinkGoogleRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.link_google(user, payload.id_token)


@router.delete(
    "/google/link",
    response_model=LinkedAccountResponse,
    summary="Unlink Google account",
    responses={
        200: {"description": "Google account unlinked successfully."},
        **_auth,
        404: {"description": "No Google account is linked."},
    },
)
async def unlink_google(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.unlink_google(user)


@router.post(
    "/telegram/link",
    response_model=LinkedAccountResponse,
    summary="Link a Telegram account",
    responses={
        200: {"description": "Telegram account linked successfully."},
        **_auth,
        409: {"description": "Conflict — this Telegram account is already linked to another user."},
    },
)
async def link_telegram(
    payload: LinkTelegramRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.link_telegram(user, payload.telegram_data)


@router.delete(
    "/telegram/link",
    response_model=LinkedAccountResponse,
    summary="Unlink Telegram account",
    responses={
        200: {"description": "Telegram account unlinked successfully."},
        **_auth,
        404: {"description": "No Telegram account is linked."},
    },
)
async def unlink_telegram(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.unlink_telegram(user)
