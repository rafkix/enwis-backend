from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import clear_auth_cookies, set_auth_cookies
from app.core.database import get_db
from app.core.rate_limit import forgot_password_limiter, login_limiter, sms_limiter, social_limiter
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    ChangePasswordRequest,
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
    SetPasswordRequest,
    SocialLoginRequest,
    TelegramNonceResponse,
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
    summary="Login (username/email + parol)",
    description=(
        "Login: username YOKI email (Gmail) + parol. Google/Telegram orqali "
        "ro'yxatdan o'tgan foydalanuvchi ham (parol o'rnatgach, `/auth/set-password`) "
        "shu yo'l bilan kira oladi; username `/users/me` da ko'rinadi."
    ),
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
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    service: AuthService = Depends(get_auth_service),
):
    # Brauzerga shu origin uchun cookie/storage'ni tozalashni buyuradi —
    # skanerda "Clear-Site-Data not configured" deb chiqqan topilma.
    response.headers["Clear-Site-Data"] = '"cookies", "storage"'
    refresh_token = (payload.refresh_token if payload else None) or request.cookies.get("refresh_token")
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
    response.headers["Clear-Site-Data"] = '"cookies", "storage"'
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


# @router.post(
#     "/forgot-password",
#     response_model=MessageResponse,
#     summary="Request password reset",
#     responses={
#         200: {"description": "Reset email sent if the address is registered."},
#         **_base,
#     },
# )
# async def forgot_password(
#     payload: ForgotPasswordRequest,
#     service: AuthService = Depends(get_auth_service),
#     _rl: None = Depends(forgot_password_limiter),
# ):
#     return await service.forgot_password(str(payload.email))


# @router.post(
#     "/reset-password",
#     response_model=MessageResponse,
#     summary="Reset password via token",
#     responses={
#         200: {"description": "Password reset successfully."},
#         **_base,
#         401: {"description": "Reset token is invalid or has expired."},
#     },
# )
# async def reset_password(
#     payload: ResetPasswordRequest,
#     service: AuthService = Depends(get_auth_service),
#     _rl: None = Depends(forgot_password_limiter),
# ):
#     return await service.reset_password(payload.token, payload.new_password)


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


@router.post(
    "/google",
    response_model=TokenResponse,
    summary="Login / register with Google (test.enwis.uz / exams.enwis.uz)",
    description=(
        "Bir chaqiriqda ham ro'yxatdan o'tkazadi (akkaunt yo'q bo'lsa), ham login "
        "qiladi (bor bo'lsa). Google'dan ism, email, avatar olinadi; username "
        "email'dan avtomatik yaratiladi. Tana: `id_token` (Google Identity Services "
        "`credential`) yoki `access_token` (`useGoogleLogin`). Javobda `is_new_user` "
        "va `username` qaytadi."
    ),
    responses={
        200: {"description": "Google authentication successful. Tokens returned."},
        **_base,
        401: {"description": "Invalid Google token."},
    },
)
async def google_auth(
    payload: SocialLoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    _rl: None = Depends(social_limiter),
):
    result = await service.google_auth(payload.id_token, request, payload.access_token)
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


@router.get(
    "/telegram/nonce",
    response_model=TelegramNonceResponse,
    summary="Telegram login nonce (ixtiyoriy, replay'dan himoya)",
    description=(
        "`Telegram.Login.init({ nonce })` ga berish uchun server tomonda yaratilgan, "
        "10 daqiqa amal qiladigan bir martalik nonce. id_token ichida nonce kelsa, "
        "`/auth/telegram` uni tekshiradi."
    ),
)
async def telegram_nonce(
    service: AuthService = Depends(get_auth_service),
    _rl: None = Depends(social_limiter),
):
    return service.issue_telegram_nonce()


@router.post(
    "/telegram",
    response_model=TokenResponse,
    summary="Login / register with Telegram (test.enwis.uz / exams.enwis.uz)",
    description=(
        "Telegram orqali login + ro'yxatdan o'tish bir chaqiriqda. Qabul qilinadi: "
        "`id_token` (yangi Telegram.Login kutubxonasi, OIDC — tavsiya etiladi), "
        "`telegram_data` (eski widget) yoki `code` + `code_verifier` + `redirect_uri` "
        "(redirect/PKCE oqimi). Telegram'dan id, ism, username, rasm va (ruxsat bo'lsa) "
        "tasdiqlangan telefon olinadi; username bo'lmasa avtomatik yaratiladi. "
        "Telefon mavjud (Eskiz SMS orqali ro'yxatdan o'tgan) akkauntniki bilan mos "
        "kelsa — bir akkauntga bog'lanadi."
    ),
    responses={
        200: {"description": "Telegram authentication successful. Tokens returned."},
        **_base,
        401: {"description": "Invalid or expired Telegram token/signature."},
    },
)
async def telegram_auth(
    payload: SocialLoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    _rl: None = Depends(social_limiter),
):
    result = await service.telegram_auth(
        request,
        id_token=payload.id_token,
        telegram_data=payload.telegram_data,
        code=payload.code,
        code_verifier=payload.code_verifier,
        redirect_uri=payload.redirect_uri,
    )
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
    _rl: None = Depends(social_limiter),
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
    return await service.link_google(user, payload.id_token, payload.access_token)


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
    return await service.link_telegram(user, payload.id_token, payload.telegram_data)


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
