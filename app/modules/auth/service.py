import logging
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import HTTPException, Request
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.email import get_reset_email_html, send_email
from app.core.exceptions import (
    AlreadyExistsException,
    InvalidCredentialsException,
    NotFoundException,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.auth.models import (
    AuthAction,
    AuthLog,
    AuthProvider,
    PasswordResetToken,
    PhoneRegistrationTicket,
    PhoneVerification,
    Role,
    Session,
    SocialAccount,
    User,
    UserStatus,
)
from app.modules.auth.providers import AbstractSMSProvider, ConsoleSMSProvider, EskizSMSProvider
from app.modules.auth.social import (
    RESERVED_USERNAMES,
    USERNAME_MAX,
    USERNAME_MIN,
    SocialAuthError,
    SocialProfile,
    consume_telegram_nonce,
    digits_only,
    google_claims_from_access_token,
    google_profile_from_claims,
    make_telegram_nonce,
    phone_variants,
    slugify_username,
    telegram_oidc,
    telegram_profile_from_claims,
    telegram_profile_from_widget,
    telegram_profile_from_webapp_user,
    verify_google_id_token_async,
    verify_telegram_webapp_init_data,
    verify_telegram_widget_payload,
)

logger = logging.getLogger(__name__)

_PHONE_LIKE = re.compile(r"^\+?[\d\s\-()]{7,20}$")
_TG_NONCE_TTL = 600


def generate_sms_code() -> str:
    return str(secrets.randbelow(900000) + 100000)


class AuthService:
    OTP_TTL_SECONDS = 300
    RESEND_COOLDOWN = 60
    MAX_ATTEMPTS = 5

    def __init__(self, db: AsyncSession):
        self.db = db

    def _now(self) -> datetime:
        from datetime import UTC

        return datetime.now(UTC).replace(tzinfo=None)

    def _hash(self, value: str) -> str:
        return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()

    def _verify_hash(self, value: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(value.encode(), hashed.encode())
        except Exception:
            return False

    def _normalize_phone(self, phone: str) -> str:
        return phone.replace(" ", "").replace("+", "").replace("-", "")

    def _make_refresh_token(self) -> tuple[str, str]:
        jti = secrets.token_urlsafe(32)
        token = f"{jti}.{secrets.token_urlsafe(64)}"
        return token, jti

    async def _generate_login_from_full_name(self, full_name: str) -> str:
        """Turns 'Ism Familiya' into login 'ism.familiya' (the only login
        app.enwis.uz users ever see or type) — falling back to a numeric
        suffix only if that exact login is already taken."""
        parts = [
            "".join(ch for ch in part.lower() if ch.isalnum())
            for part in full_name.strip().split()
            if part.strip()
        ]
        base = ".".join(parts)[:28] or "user"

        result = await self.db.execute(select(User.id).where(User.username == base))
        if not result.scalar_one_or_none():
            return base

        while True:
            candidate = f"{base}{secrets.randbelow(10000)}"
            result = await self.db.execute(select(User.id).where(User.username == candidate))
            if not result.scalar_one_or_none():
                return candidate

    async def _log(
        self,
        user_id: str | None,
        action: AuthAction,
        request: Request | None = None,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        try:
            log_entry = AuthLog(
                user_id=uuid.UUID(user_id) if user_id else None,
                action=action,
                status=status,
                error_message=error,
                ip_address=request.client.host if request and request.client else None,
                user_agent=request.headers.get("user-agent") if request else None,
            )
            self.db.add(log_entry)
            await self.db.flush()
        except Exception as exc:
            logger.warning("Failed to write auth log: %s", exc)

    async def _attach_default_role(self, user: User) -> None:
        result = await self.db.execute(select(Role).where(Role.name == "USER"))
        role = result.scalar_one_or_none()
        if not role:
            role = Role(name="USER", description="Default user role")
            self.db.add(role)
            await self.db.flush()
        await self.db.refresh(user, attribute_names=["roles"])
        if role not in user.roles:
            user.roles.append(role)

    def _parse_device_name(self, user_agent: str | None) -> str | None:
        if not user_agent:
            return None
        ua = user_agent.lower()
        if "yabrowser" in ua or "yandex" in ua:
            return "Yandex Browser"
        if "chrome" in ua and "edg" not in ua:
            return "Chrome"
        if "firefox" in ua:
            return "Firefox"
        if "safari" in ua and "chrome" not in ua:
            return "Safari"
        if "edg" in ua:
            return "Edge"
        if "opera" in ua or "opr" in ua:
            return "Opera"
        if "mobile" in ua:
            return "Mobile Browser"
        return "Unknown"

    async def _create_session(self, user: User, request: Request) -> dict:
        access = create_access_token({"sub": str(user.id)})
        refresh, jti = self._make_refresh_token()
        user_agent = request.headers.get("user-agent")
        session = Session(
            user_id=user.id,
            refresh_token_jti=jti,
            refresh_token_hash=self._hash(refresh),
            expires_at=self._now() + timedelta(days=settings.REFRESH_TOKEN_DAYS),
            ip_address=request.client.host if request.client else None,
            user_agent=user_agent,
            device_name=self._parse_device_name(user_agent),
        )
        self.db.add(session)
        user.last_login_at = self._now()
        await self._log(str(user.id), AuthAction.LOGIN, request)
        await self.db.commit()
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_MINUTES * 60,
        }

    # NOTE: registration is a ONE-TIME event on app.enwis.uz and happens
    # exclusively through the SMS-verified flow below
    # (`register_send_code` -> `register_verify`). There is no
    # separate "register without SMS" path anymore — that used to exist
    # as a second, parallel flow (`/auth/register` with an optional
    # ticket) and was a major source of confusion. See
    # `register_send_code` / `register_verify`.

    async def _find_user_for_login(self, identifier: str) -> User | None:
        """Login identifikatori: username YOKI email (parol bilan). Telefon raqami
        — app.enwis.uz'da login'ini unutganlar uchun zaxira yo'l (avvalgidek)."""
        raw = identifier.strip()
        ident = raw.lower()
        if not ident:
            return None

        # Username'da '@' bo'lishi mumkin emas, shuning uchun '@' bor bo'lsa — email.
        cond = User.email == ident if "@" in ident else User.username == ident
        result = await self.db.execute(
            select(User).options(selectinload(User.roles)).where(cond).limit(1)
        )
        user = result.unique().scalars().first()

        if user is None and "@" not in ident and _PHONE_LIKE.fullmatch(raw):
            result = await self.db.execute(
                select(User)
                .options(selectinload(User.roles))
                .where(User.phone.in_(phone_variants(raw)))
                .limit(1)
            )
            user = result.unique().scalars().first()
        return user

    async def login(self, username: str, password: str, request: Request) -> dict:
        user = await self._find_user_for_login(username)

        # Soft-delete qilingan akkaunt yo'q deb hisoblanadi (mavjudligi oshkor bo'lmaydi).
        if not user or user.deleted_at is not None or not user.password_hash:
            await self._log(None, AuthAction.LOGIN, request, "failed", "Invalid login")
            await self.db.commit()
            raise InvalidCredentialsException()

        is_valid, needs_rehash = verify_password(password, user.password_hash)
        if not is_valid:
            await self._log(str(user.id), AuthAction.LOGIN, request, "failed", "Invalid password")
            await self.db.commit()
            raise InvalidCredentialsException()

        if needs_rehash:
            user.password_hash = hash_password(password)

        self._ensure_can_login(user)
        return await self._create_session(user, request)

    async def refresh(
        self,
        refresh_token: str,
        request: Request | None = None,
    ) -> dict:
        try:
            jti, _ = refresh_token.split(".", 1)
        except ValueError:
            raise HTTPException(401, "Malformed token") from None
        result = await self.db.execute(
            select(Session).where(
                Session.refresh_token_jti == jti,
                Session.is_revoked.is_(False),
                Session.expires_at > self._now(),
            )
        )
        session = result.scalar_one_or_none()

        if not session or not self._verify_hash(refresh_token, session.refresh_token_hash):
            raise HTTPException(401, "Invalid refresh token")

        session.is_revoked = True
        new_refresh, new_jti = self._make_refresh_token()
        self.db.add(
            Session(
                user_id=session.user_id,
                refresh_token_jti=new_jti,
                refresh_token_hash=self._hash(new_refresh),
                expires_at=self._now() + timedelta(days=settings.REFRESH_TOKEN_DAYS),
                ip_address=request.client.host if request and request.client else None,
                user_agent=request.headers.get("user-agent") if request else None,
            )
        )
        access = create_access_token({"sub": str(session.user_id)})
        await self._log(str(session.user_id), AuthAction.REFRESH, request)
        await self.db.commit()
        return {
            "access_token": access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_MINUTES * 60,
        }

    async def logout(self, refresh_token: str) -> dict:
        try:
            jti, _ = refresh_token.split(".", 1)
        except ValueError:
            raise HTTPException(401, "Malformed token") from None
        result = await self.db.execute(
            select(Session).where(
                Session.refresh_token_jti == jti,
                Session.is_revoked.is_(False),
            )
        )
        session = result.scalar_one_or_none()
        if session and self._verify_hash(refresh_token, session.refresh_token_hash):
            session.is_revoked = True
            await self._log(str(session.user_id), AuthAction.LOGOUT)
            await self.db.commit()
        return {"success": True, "message": "Logged out"}

    async def logout_all(self, user: User) -> dict:
        await self.db.execute(
            update(Session).where(Session.user_id == user.id).values(is_revoked=True)
        )
        await self.db.commit()
        return {"success": True, "message": "All sessions have been revoked"}

    async def set_password(self, user: User, new_password: str) -> dict:
        if user.password_hash:
            raise HTTPException(400, "Password already set. Use change_password instead.")
        user.password_hash = hash_password(new_password)
        await self.db.commit()
        return {"success": True, "message": "Password set"}

    async def change_password(self, user: User, current_password: str, new_password: str) -> dict:
        if not user.password_hash:
            raise HTTPException(400, "No password set. Use set_password instead.")
        is_valid, _ = verify_password(current_password, user.password_hash)
        if not is_valid:
            raise HTTPException(400, "Current password is incorrect")
        user.password_hash = hash_password(new_password)
        await self._log(str(user.id), AuthAction.PASSWORD_CHANGE)
        await self.db.commit()
        return {"success": True, "message": "Password changed"}

    async def forgot_password(self, email: str) -> dict:
        result = await self.db.execute(select(User).where(User.email == email.lower()))
        user = result.scalar_one_or_none()
        generic = {
            "success": True,
            "message": "If the email is registered, a reset link has been sent",
        }
        if not user:
            return generic

        await self.db.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
        token = PasswordResetToken(
            user_id=user.id,
            token=PasswordResetToken.generate_token(),
            expires_at=self._now() + timedelta(hours=1),
        )
        self.db.add(token)
        await self.db.commit()

        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token.token}"
        try:
            await send_email(
                to=user.email,
                subject="Reset your password",
                body=get_reset_email_html(reset_link),
            )
        except Exception as exc:
            logger.warning("Failed to send reset email: %s", exc)
        return generic

    async def reset_password(self, token: str, new_password: str) -> dict:
        result = await self.db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.is_used.is_(False),
            )
        )
        reset_token = result.scalar_one_or_none()
        if not reset_token or reset_token.is_expired:
            raise HTTPException(400, "Token is invalid or has expired")

        user_result = await self.db.execute(select(User).where(User.id == reset_token.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User")

        user.password_hash = hash_password(new_password)
        reset_token.is_used = True
        await self.db.execute(
            update(Session).where(Session.user_id == user.id).values(is_revoked=True)
        )
        await self.db.commit()
        return {"success": True, "message": "Password reset successfully"}

    async def forgot_password_send_code(self, phone: str, request: Request) -> dict:
        """app.enwis.uz — parolni tiklash, 1-qadam: telefon bo'yicha
        akkaunt topilsa SMS kod yuboriladi. Javob har doim generic —
        akkaunt mavjudligini oshkor qilmaslik uchun (email variantidagi
        kabi), lekin real amalda faqat topilgan holatda SMS ketadi."""
        phone = self._normalize_phone(phone)
        generic = {
            "success": True,
            "message": "Agar bu raqam ro'yxatdan o'tgan bo'lsa, tasdiqlash kodi yuborildi",
        }

        result = await self.db.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()
        if not user:
            return generic

        result = await self.db.execute(
            select(PhoneVerification)
            .where(
                PhoneVerification.user_id == user.id,
                PhoneVerification.phone == phone,
                PhoneVerification.is_used.is_(False),
            )
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()
        if last:
            diff = (self._now() - last.created_at).total_seconds()
            if diff < self.RESEND_COOLDOWN:
                # Generic javob bilan bir xilda qoladi — hech narsa oshkor
                # qilinmaydi, lekin haqiqatda yangi kod yuborilmaydi.
                return generic
            last.is_used = True

        code = generate_sms_code()
        verification = PhoneVerification(
            user_id=user.id,
            phone=phone,
            code_hash=self._hash(code),
            expires_at=self._now() + timedelta(seconds=self.OTP_TTL_SECONDS),
        )
        self.db.add(verification)
        await self.db.commit()

        try:
            await self._send_sms_code(phone, code)
        except Exception as exc:
            logger.error("Parolni tiklash SMS'i yuborilmadi (phone=%s): %s", phone, exc)
            verification.is_used = True
            await self.db.commit()
            # Bu yerda ham javob generic bo'lib qoladi — chunki foydalanuvchi
            # bormi-yo'qmi bilinmasligi kerak. Real yuborilmagan xatolik
            # loglarda qoladi, operatsion jihatdan kuzatiladi.

        return generic

    async def forgot_password_reset(
        self, phone: str, code: str, new_password: str, request: Request
    ) -> dict:
        """2-qadam: SMS kodni tasdiqlaydi va bir chaqiriqning o'zida yangi
        parolni o'rnatadi (email oqimidagi kabi alohida token bosqichi
        shart emas — kod o'zi shu vazifani bajaradi)."""
        phone = self._normalize_phone(phone)

        result = await self.db.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(400, "Kod noto'g'ri yoki muddati o'tgan")

        result = await self.db.execute(
            select(PhoneVerification)
            .where(
                PhoneVerification.user_id == user.id,
                PhoneVerification.phone == phone,
                PhoneVerification.is_used.is_(False),
            )
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
        verification = result.scalar_one_or_none()
        if not verification:
            raise HTTPException(400, "Kod so'ralmagan. Avval kod yuborishni so'rang.")

        expires_at = verification.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if self._now() > expires_at:
            verification.is_used = True
            await self.db.commit()
            raise HTTPException(410, "Kod muddati o'tgan. Qaytadan so'rang.")

        if verification.attempts >= self.MAX_ATTEMPTS:
            verification.is_used = True
            await self.db.commit()
            raise HTTPException(429, "Juda ko'p urinish. Qaytadan kod so'rang.")

        if not self._verify_hash(code, verification.code_hash):
            verification.attempts += 1
            await self.db.commit()
            remaining = self.MAX_ATTEMPTS - verification.attempts
            raise HTTPException(400, f"Kod noto'g'ri. {remaining} urinish qoldi.")

        verification.is_used = True
        user.password_hash = hash_password(new_password)
        # Parol almashtirilgach barcha eski sessiyalar bekor qilinadi —
        # xuddi email orqali reset qilingandagi kabi.
        await self.db.execute(
            update(Session).where(Session.user_id == user.id).values(is_revoked=True)
        )
        await self._log(str(user.id), AuthAction.PASSWORD_CHANGE, request)
        await self.db.commit()
        return {"success": True, "message": "Parol muvaffaqiyatli yangilandi"}

    async def _send_sms_code(self, phone: str, code: str) -> None:
        # FIX: exception endi yutilmaydi va chaqiruvchiga ko'tariladi.
        # Avval bu yerda try/except bilan xato faqat log qilinib,
        # keyin hech narsa qilinmasdi — natijada SMS yetib bormasa ham
        # chaqiruvchi (register_send_code) buni bilmay 200 OK qaytarardi.
        provider: AbstractSMSProvider = (
            EskizSMSProvider() if settings.ESKIZ_EMAIL else ConsoleSMSProvider()
        )
        await provider.send_otp(phone, code)

    async def register_send_code(
        self, full_name: str, phone: str, password: str, request: Request
    ) -> dict:
        """Step 1 of the one-time app.enwis.uz registration: collect
        full name + phone + password up front, send a 6-digit SMS code.
        Call `register_verify` with the same phone + the code to finish."""
        phone = self._normalize_phone(phone)

        result = await self.db.execute(select(User.id).where(User.phone == phone))
        if result.scalar_one_or_none():
            raise AlreadyExistsException("User")

        result = await self.db.execute(
            select(PhoneRegistrationTicket)
            .where(
                PhoneRegistrationTicket.phone == phone,
                PhoneRegistrationTicket.is_used.is_(False),
            )
            .order_by(PhoneRegistrationTicket.created_at.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()
        if last:
            diff = (self._now() - last.created_at).total_seconds()
            if diff < self.RESEND_COOLDOWN:
                wait = int(self.RESEND_COOLDOWN - diff)
                raise HTTPException(429, f"Please wait {wait}s before a new code")
            last.is_used = True

        code = generate_sms_code()
        ticket = PhoneRegistrationTicket(
            phone=phone,
            code_hash=self._hash(code),
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            expires_at=self._now() + timedelta(seconds=self.OTP_TTL_SECONDS),
        )
        self.db.add(ticket)
        await self.db.commit()

        self.db.add(
            AuthLog(
                user_id=None,
                action=AuthAction.REGISTER,
                status="pending",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent") if request else None,
            )
        )
        await self.db.commit()

        # FIX: SMS yuborish endi try/except bilan o'raladi. Muvaffaqiyatsiz
        # bo'lsa: (1) ticket darhol is_used=True qilinadi — aks holda
        # keyingi urinish 60s RESEND_COOLDOWN'ga tushib qoladi va
        # foydalanuvchi hech qachon kod ololmaydi (cheksiz "kutish" tsikli);
        # (2) foydalanuvchiga aniq 502 xatosi qaytariladi — "success: True"
        # deb aldab qo'yilmaydi.
        try:
            await self._send_sms_code(phone, code)
        except Exception as exc:
            logger.error("SMS yuborilmadi (phone=%s), ticket bekor qilindi: %s", phone, exc)
            ticket.is_used = True
            await self.db.commit()
            raise HTTPException(
                502,
                "SMS yuborishda xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring.",
            ) from exc

        return {
            "success": True,
            "message": f"Code sent. Valid for {self.OTP_TTL_SECONDS // 60} minutes.",
        }

    async def register_verify(self, phone: str, code: str, request: Request) -> dict:
        """Step 2 (final): confirm the SMS code and create the account.
        The login (username) is generated automatically from the full
        name collected in step 1 — the user never has to invent one."""
        phone = self._normalize_phone(phone)

        result = await self.db.execute(
            select(PhoneRegistrationTicket)
            .where(
                PhoneRegistrationTicket.phone == phone,
                PhoneRegistrationTicket.is_used.is_(False),
            )
            .order_by(PhoneRegistrationTicket.created_at.desc())
            .limit(1)
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise HTTPException(400, "No verification found. Request a new code.")

        if ticket.is_expired:
            ticket.is_used = True
            await self.db.commit()
            raise HTTPException(410, "Code has expired. Request a new code.")

        if ticket.attempts >= self.MAX_ATTEMPTS:
            ticket.is_used = True
            await self.db.commit()
            raise HTTPException(429, "Too many attempts. Request a new code.")

        if not self._verify_hash(code, ticket.code_hash):
            ticket.attempts += 1
            await self.db.commit()
            remaining = self.MAX_ATTEMPTS - ticket.attempts
            raise HTTPException(400, f"Incorrect code. {remaining} attempt(s) left.")

        if not ticket.full_name or not ticket.password_hash:
            raise HTTPException(400, "Registration data missing. Start over from send-code.")

        ticket.is_used = True

        login = await self._generate_login_from_full_name(ticket.full_name)

        user = User(
            username=login,
            full_name=ticket.full_name,
            phone=phone,
            phone_verified=True,
            password_hash=ticket.password_hash,
            status=UserStatus.ACTIVE,
            is_active=True,
            is_verified=True,
        )
        self.db.add(user)
        await self.db.flush()
        await self._attach_default_role(user)
        await self._log(str(user.id), AuthAction.REGISTER, request)
        await self.db.commit()

        result = await self._create_session(user, request)
        result["username"] = login
        return result

    # ──────────────────────────────────────────────────────────────────
    # Social login (Google / Telegram) — test.enwis.uz, exams.enwis.uz,
    # web3.enwis.uz (Mini App). Hammasi bitta `_social_login` quvuriga
    # tushadi: tokenni tekshir -> SocialProfile -> topish/bog'lash/yaratish.
    # ──────────────────────────────────────────────────────────────────

    def _ensure_can_login(self, user: User) -> None:
        if user.deleted_at is not None:
            raise HTTPException(403, "Account has been deleted")
        if user.status == UserStatus.BLOCKED:
            raise HTTPException(403, "User is blocked")
        if not user.is_active:
            raise HTTPException(403, "User is not active")

    # ── provider tokenlarini tekshirish -> SocialProfile ────────────────

    async def _google_profile(
        self, id_token_str: str | None, access_token: str | None = None
    ) -> SocialProfile:
        try:
            if id_token_str:
                claims = await verify_google_id_token_async(
                    id_token_str, settings.google_client_ids
                )
            elif access_token:
                claims = await google_claims_from_access_token(
                    access_token, settings.google_client_ids
                )
            else:
                raise HTTPException(400, "id_token or access_token is required")
            return google_profile_from_claims(claims)
        except SocialAuthError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc

    def _check_telegram_nonce(self, claims: dict) -> None:
        nonce = claims.get("nonce")
        if nonce is None:
            if settings.TELEGRAM_REQUIRE_NONCE:
                raise SocialAuthError("Telegram nonce is required")
            return
        if not consume_telegram_nonce(nonce, self._nonce_secret(), _TG_NONCE_TTL):
            raise SocialAuthError("Telegram nonce is invalid, expired or already used")

    @staticmethod
    def _nonce_secret() -> str:
        return f"{settings.JWT_SECRET}:telegram-nonce"

    def issue_telegram_nonce(self) -> dict:
        return {"nonce": make_telegram_nonce(self._nonce_secret()), "expires_in": _TG_NONCE_TTL}

    async def _telegram_profile(
        self,
        *,
        id_token_str: str | None = None,
        telegram_data: dict | None = None,
        code: str | None = None,
        code_verifier: str | None = None,
        redirect_uri: str | None = None,
    ) -> SocialProfile:
        """Telegram'ning uchala yo'li ham bir xil `SocialProfile` beradi:
        1) `id_token`  — yangi Telegram.Login kutubxonasi (OIDC, tavsiya etiladi)
        2) `code`      — OIDC Authorization Code + PKCE (redirect oqimi)
        3) `telegram_data` — eski iframe widget (HMAC)
        """
        try:
            if code:
                if not redirect_uri:
                    raise HTTPException(400, "redirect_uri is required together with code")
                raw = await telegram_oidc.exchange_code(
                    code=code,
                    redirect_uri=redirect_uri,
                    client_id=settings.telegram_client_id,
                    client_secret=settings.TELEGRAM_CLIENT_SECRET,
                    code_verifier=code_verifier,
                )
                claims = await telegram_oidc.verify_id_token(raw, settings.telegram_client_id)
                return telegram_profile_from_claims(claims)  # state+PKCE frontend'da

            if id_token_str:
                claims = await telegram_oidc.verify_id_token(
                    id_token_str, settings.telegram_client_id
                )
                self._check_telegram_nonce(claims)
                return telegram_profile_from_claims(claims)

            if telegram_data:
                data = verify_telegram_widget_payload(
                    telegram_data, settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_AUTH_MAX_AGE
                )
                return telegram_profile_from_widget(data)

            raise HTTPException(400, "id_token, telegram_data or code is required")
        except SocialAuthError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc

    # ── DB yordamchilari ────────────────────────────────────────────────

    async def _first_user(self, *conditions) -> User | None:
        result = await self.db.execute(
            select(User).options(selectinload(User.roles)).where(*conditions).limit(1)
        )
        return result.unique().scalars().first()

    async def _username_taken(self, username: str) -> bool:
        if username in RESERVED_USERNAMES:
            return True
        res = await self.db.execute(select(User.id).where(User.username == username))
        return res.scalar_one_or_none() is not None

    async def _email_taken(self, email: str, exclude: uuid.UUID | None = None) -> bool:
        stmt = select(User.id).where(User.email == email.lower())
        if exclude:
            stmt = stmt.where(User.id != exclude)
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none() is not None

    async def _phone_taken(self, phone: str, exclude: uuid.UUID | None = None) -> bool:
        stmt = select(User.id).where(User.phone.in_(phone_variants(phone)))
        if exclude:
            stmt = stmt.where(User.id != exclude)
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none() is not None

    async def _unique_username(self, profile: SocialProfile) -> str:
        """Username'ni avtomatik yaratadi (login = username + parol uchun ham
        shu ishlatiladi), faqat [a-z0-9._], 3–30 belgi:

        Telegram: @username (bo'lsa) -> to'liq ism -> 'user' + raqamlar
        Google:   email'ning '@' dan oldingi qismi -> to'liq ism -> 'user' + raqamlar
        Band bo'lsa — oxiriga tasodifiy raqamlar qo'shiladi.
        """
        raw_bases: list[str] = []
        if profile.username_hint:
            raw_bases.append(profile.username_hint)
        if profile.email:
            raw_bases.append(profile.email.split("@", 1)[0])
        if profile.full_name:
            raw_bases.append(profile.full_name)

        slugs = [slugify_username(b) for b in raw_bases]
        slugs = [sl for sl in slugs if len(sl) >= USERNAME_MIN]

        for slug in slugs:
            if not await self._username_taken(slug):
                return slug

        stem = slugs[0] if slugs else "user"
        for width in (2, 3, 4, 6):
            for _ in range(5):
                suffix = "".join(secrets.choice("0123456789") for _ in range(width))
                candidate = f"{stem[: USERNAME_MAX - width]}{suffix}"
                if not await self._username_taken(candidate):
                    return candidate
        return f"user{secrets.token_hex(8)}"

    @staticmethod
    def _provider_columns(provider: AuthProvider) -> tuple[str, str]:
        if provider == AuthProvider.GOOGLE:
            return "google_id", "is_google_verified"
        return "telegram_id", "is_telegram_verified"

    async def _linked_to_other_identity(
        self, user: User, provider: AuthProvider, provider_id: str
    ) -> bool:
        """Foydalanuvchida shu provider'ning BOSHQA akkaunti allaqachon bog'langanmi?"""
        id_col, _ = self._provider_columns(provider)
        current = getattr(user, id_col)
        if current and current != provider_id:
            return True
        res = await self.db.execute(
            select(SocialAccount.id).where(
                SocialAccount.user_id == user.id,
                SocialAccount.provider == provider,
                SocialAccount.provider_id != provider_id,
            )
        )
        return res.first() is not None

    async def _find_social_user(self, profile: SocialProfile, provider: AuthProvider) -> User | None:
        pid = profile.provider_id

        # 1) Aniq bog'langan hisob.
        res = await self.db.execute(
            select(SocialAccount)
            .options(selectinload(SocialAccount.user).selectinload(User.roles))
            .where(SocialAccount.provider == provider, SocialAccount.provider_id == pid)
        )
        account = res.scalar_one_or_none()
        if account:
            return account.user

        # 2) Eski qatorlar: users.google_id / users.telegram_id bor, SocialAccount yo'q.
        id_col, _ = self._provider_columns(provider)
        user = await self._first_user(getattr(User, id_col) == pid)
        if user:
            return user

        # 3) TASDIQLANGAN email (Google) — shu email bilan ro'yxatdan o'tgan akkauntga bog'laymiz.
        if profile.email and profile.email_verified:
            user = await self._first_user(User.email == profile.email)
            if user and not await self._linked_to_other_identity(user, provider, pid):
                return user

        # 4) TASDIQLANGAN telefon (Telegram) — Eskiz SMS orqali ro'yxatdan o'tgan
        #    akkaunt bilan bir xil raqam bo'lsa, ikkalasi bitta akkaunt.
        if profile.phone and profile.phone_verified:
            user = await self._first_user(
                User.phone.in_(phone_variants(profile.phone)),
                User.phone_verified.is_(True),
            )
            if user and not await self._linked_to_other_identity(user, provider, pid):
                return user

        return None

    async def _link_and_fill(self, user: User, profile: SocialProfile, provider: AuthProvider) -> None:
        """Provider'ni akkauntga bog'laydi va FAQAT bo'sh maydonlarni to'ldiradi
        (foydalanuvchi o'zi kiritgan ism/email/avatarni hech qachon bosib ketmaydi)."""
        pid = profile.provider_id
        id_col, verified_col = self._provider_columns(provider)

        res = await self.db.execute(
            select(SocialAccount).where(
                SocialAccount.user_id == user.id, SocialAccount.provider == provider
            )
        )
        account = res.scalars().first()
        if account is None:
            self.db.add(
                SocialAccount(
                    user_id=user.id,
                    provider=provider,
                    provider_id=pid,
                    email=profile.email,
                    email_verified=profile.email_verified,
                )
            )
        elif profile.email and (account.email != profile.email or not account.email_verified):
            account.email = profile.email
            account.email_verified = profile.email_verified

        if not getattr(user, id_col):
            setattr(user, id_col, pid)
        setattr(user, verified_col, True)
        user.is_verified = True

        if not user.full_name and profile.full_name:
            user.full_name = profile.full_name[:255]
        if not user.avatar and profile.avatar and len(profile.avatar) <= 500:
            user.avatar = profile.avatar
        if (
            not user.email
            and profile.email
            and profile.email_verified
            and not await self._email_taken(profile.email, exclude=user.id)
        ):
            user.email = profile.email

        if profile.phone:
            if user.phone:
                if digits_only(user.phone) == profile.phone and profile.phone_verified:
                    user.phone_verified = True
            elif profile.phone_verified and not await self._phone_taken(
                profile.phone, exclude=user.id
            ):
                user.phone = profile.phone
                user.phone_verified = True

    async def _create_social_user(
        self, profile: SocialProfile, provider: AuthProvider, request: Request
    ) -> User:
        email = None
        if profile.email and profile.email_verified and not await self._email_taken(profile.email):
            email = profile.email
        phone = None
        if (
            profile.phone
            and profile.phone_verified
            and not await self._phone_taken(profile.phone)
        ):
            phone = profile.phone

        id_col, verified_col = self._provider_columns(provider)
        user = User(
            username=await self._unique_username(profile),
            email=email,
            full_name=profile.full_name[:255] if profile.full_name else None,
            avatar=profile.avatar if profile.avatar and len(profile.avatar) <= 500 else None,
            phone=phone,
            phone_verified=bool(phone),
            is_verified=True,
            status=UserStatus.ACTIVE,
            is_active=True,
            **{id_col: profile.provider_id, verified_col: True},
        )
        self.db.add(user)
        await self.db.flush()
        await self._attach_default_role(user)
        self.db.add(
            SocialAccount(
                user_id=user.id,
                provider=provider,
                provider_id=profile.provider_id,
                email=profile.email,
                email_verified=profile.email_verified,
            )
        )
        await self._log(str(user.id), AuthAction.REGISTER, request)
        return user

    async def _resolve_social_user(
        self, profile: SocialProfile, request: Request
    ) -> tuple[User, bool]:
        provider = AuthProvider(profile.provider)
        user = await self._find_social_user(profile, provider)
        if user is not None:
            self._ensure_can_login(user)  # bloklangan akkauntga hech narsa bog'lanmaydi
            await self._link_and_fill(user, profile, provider)
            is_new = False
        else:
            user = await self._create_social_user(profile, provider, request)
            is_new = True
        await self.db.commit()
        return user, is_new

    async def _social_login(self, profile: SocialProfile, request: Request) -> dict:
        user: User | None = None
        is_new = False
        for attempt in (1, 2):
            try:
                user, is_new = await self._resolve_social_user(profile, request)
                break
            except IntegrityError:
                # Parallel ikkita birinchi-kirish (yoki username poygasi): tranzaksiyani
                # bekor qilib, qayta topamiz — ikkinchi urinishda akkaunt allaqachon bor.
                await self.db.rollback()
                if attempt == 2:
                    logger.exception("Social login integrity error (%s)", profile.provider)
                    raise HTTPException(409, "Could not complete sign-in, please retry") from None
        assert user is not None
        result = await self._create_session(user, request)
        result["username"] = user.username
        result["is_new_user"] = is_new
        return result

    # ── ochiq (public) metodlar ─────────────────────────────────────────

    async def google_auth(
        self, id_token_str: str | None, request: Request, access_token: str | None = None
    ) -> dict:
        profile = await self._google_profile(id_token_str, access_token)
        return await self._social_login(profile, request)

    async def telegram_auth(
        self,
        request: Request,
        *,
        id_token: str | None = None,
        telegram_data: dict | None = None,
        code: str | None = None,
        code_verifier: str | None = None,
        redirect_uri: str | None = None,
    ) -> dict:
        """test.enwis.uz / exams.enwis.uz: Telegram login (id_token | widget | code)."""
        profile = await self._telegram_profile(
            id_token_str=id_token,
            telegram_data=telegram_data,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        return await self._social_login(profile, request)

    async def telegram_webapp_auth(self, init_data: str, request: Request) -> dict:
        """web3.enwis.uz (Telegram Mini App): ochilishning o'zi = login."""
        try:
            tg_user = verify_telegram_webapp_init_data(
                init_data, settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_AUTH_MAX_AGE
            )
            profile = telegram_profile_from_webapp_user(tg_user)
        except SocialAuthError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        return await self._social_login(profile, request)

    async def _link_social(self, user: User, profile: SocialProfile) -> dict:
        provider = AuthProvider(profile.provider)
        pid = profile.provider_id
        id_col, _ = self._provider_columns(provider)
        label = "Google" if provider == AuthProvider.GOOGLE else "Telegram"

        res = await self.db.execute(
            select(SocialAccount).where(
                SocialAccount.provider == provider, SocialAccount.provider_id == pid
            )
        )
        account = res.scalar_one_or_none()
        if account and account.user_id != user.id:
            raise HTTPException(409, f"This {label} account is already linked")
        if account is None:
            owner = await self.db.execute(
                select(User.id).where(getattr(User, id_col) == pid, User.id != user.id)
            )
            if owner.first() is not None:
                raise HTTPException(409, f"This {label} account is already linked")
        if account is None and await self._linked_to_other_identity(user, provider, pid):
            raise HTTPException(
                409, f"A different {label} account is already linked — unlink it first"
            )

        await self._link_and_fill(user, profile, provider)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, f"This {label} account is already linked") from None
        return {"provider": provider.value, "linked": True, "email": profile.email}

    async def link_google(
        self, user: User, id_token_str: str | None = None, access_token: str | None = None
    ) -> dict:
        profile = await self._google_profile(id_token_str, access_token)
        return await self._link_social(user, profile)

    async def unlink_google(self, user: User) -> dict:
        await self._unlink_provider(user, AuthProvider.GOOGLE)
        user.google_id = None
        await self.db.commit()
        return {"provider": "google", "linked": False, "email": None}

    async def link_telegram(
        self,
        user: User,
        id_token_str: str | None = None,
        telegram_data: dict | None = None,
    ) -> dict:
        profile = await self._telegram_profile(
            id_token_str=id_token_str, telegram_data=telegram_data
        )
        return await self._link_social(user, profile)

    async def unlink_telegram(self, user: User) -> dict:
        await self._unlink_provider(user, AuthProvider.TELEGRAM)
        user.telegram_id = None
        await self.db.commit()
        return {"provider": "telegram", "linked": False, "email": None}

    async def _unlink_provider(self, user: User, provider: AuthProvider) -> None:
        result = await self.db.execute(
            select(SocialAccount).where(
                SocialAccount.user_id == user.id,
                SocialAccount.provider == provider,
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            raise NotFoundException("Linked account")
        other_accounts = await self.db.execute(
            select(SocialAccount.id).where(
                SocialAccount.user_id == user.id,
                SocialAccount.provider != provider,
            )
        )
        if not user.password_hash and not other_accounts.scalar_one_or_none():
            raise HTTPException(
                400,
                "Set a password before unlinking your only sign-in",
            )
        await self.db.execute(delete(SocialAccount).where(SocialAccount.id == account.id))
