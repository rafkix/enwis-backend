import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta

import bcrypt
from fastapi import HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.email import get_reset_email_html, send_email
from app.core.exceptions import (
    AlreadyExistsException,
    InvalidCredentialsException,
    NotFoundException,
)
from app.core.plans import PlanTier, get_plan_features
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.auth.models import (
    AuthAction,
    AuthLog,
    AuthProvider,
    PasswordResetToken,
    PhoneRegistrationTicket,
    Role,
    Session,
    SocialAccount,
    User,
    UserStatus,
)
from app.modules.auth.providers import AbstractSMSProvider, ConsoleSMSProvider, EskizSMSProvider

logger = logging.getLogger(__name__)


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

    async def _generate_unique_username(self, base: str | None = None) -> str:
        clean_base = (base or "user").lower()
        clean_base = "".join(ch for ch in clean_base if ch.isalnum() or ch == "_")
        clean_base = clean_base[:32] or "user"
        while True:
            username = f"{clean_base}_{secrets.randbelow(10000)}"
            result = await self.db.execute(
                select(User.id).where(User.username == username)
            )
            if not result.scalar_one_or_none():
                return username

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
            result = await self.db.execute(
                select(User.id).where(User.username == candidate)
            )
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

    async def login(self, username: str, password: str, request: Request) -> dict:
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.username == username.lower())
        )
        user = result.unique().scalar_one_or_none()

        if not user or not user.password_hash:
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

        if user.status == UserStatus.BLOCKED:
            raise HTTPException(403, "User is blocked")
        if not user.is_active:
            raise HTTPException(403, "User is not active")

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

        user_result = await self.db.execute(
            select(User).where(User.id == reset_token.user_id)
        )
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

    async def _send_sms_code(self, phone: str, code: str) -> None:
        try:
            provider: AbstractSMSProvider = (
                EskizSMSProvider() if settings.ESKIZ_EMAIL else ConsoleSMSProvider()
            )
            await provider.send_otp(phone, code)
        except Exception as exc:
            logger.error("Failed to send SMS to %s: %s", phone, exc)

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
        self.db.add(
            PhoneRegistrationTicket(
                phone=phone,
                code_hash=self._hash(code),
                full_name=full_name.strip(),
                password_hash=hash_password(password),
                expires_at=self._now() + timedelta(seconds=self.OTP_TTL_SECONDS),
            )
        )
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
        await self._send_sms_code(phone, code)
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

        return await self._create_session(user, request)

    def _verify_google_token(self, token: str) -> dict:
        try:
            return id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except Exception as exc:
            logger.warning("Invalid Google token: %s", exc)
            raise HTTPException(401, "Invalid Google token") from exc

    async def google_auth(self, id_token_str: str, request: Request) -> dict:
        google_data = self._verify_google_token(id_token_str)
        provider_id = google_data["sub"]
        email = google_data.get("email", "").lower()

        result = await self.db.execute(
            select(SocialAccount)
            .options(selectinload(SocialAccount.user).selectinload(User.roles))
            .where(
                SocialAccount.provider == AuthProvider.GOOGLE,
                SocialAccount.provider_id == provider_id,
            )
        )
        account = result.scalar_one_or_none()
        if account:
            user = account.user
            if not user.is_google_verified:
                user.is_google_verified = True
                await self.db.commit()
            return await self._create_session(user, request)

        user = None
        if email:
            user_result = await self.db.execute(
                select(User).options(selectinload(User.roles)).where(User.email == email)
            )
            user = user_result.scalar_one_or_none()

        if not user:
            base_username = email.split("@")[0] if email else None
            user = User(
                username=await self._generate_unique_username(base_username),
                email=email or None,
                full_name=google_data.get("name"),
                avatar=google_data.get("picture"),
                google_id=provider_id,
                is_google_verified=True,
                is_verified=True,
                status=UserStatus.ACTIVE,
                is_active=True,
            )
            self.db.add(user)
            await self.db.flush()
            await self._attach_default_role(user)
        elif not user.google_id:
            user.google_id = provider_id
            user.is_google_verified = True

        self.db.add(
            SocialAccount(
                user_id=user.id,
                provider=AuthProvider.GOOGLE,
                provider_id=provider_id,
                email=email or None,
                email_verified=google_data.get("email_verified", False),
            )
        )
        await self.db.commit()
        return await self._create_session(user, request)

    def _verify_telegram_data(self, data: dict) -> dict:
        data = data.copy()
        check_hash = data.pop("hash", None)
        if not check_hash:
            raise HTTPException(401, "Missing Telegram hash")
        data_check = "\n".join(str(value) for value in data.values())
        secret = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
        calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, check_hash):
            raise HTTPException(401, "Invalid Telegram signature")
        return data

    async def telegram_auth(self, payload: dict, request: Request) -> dict:
        """Telegram LOGIN WIDGET flow (test.enwis.uz web button) — data
        comes from the widget's JS callback, hash uses secret =
        SHA256(bot_token)."""
        telegram_data = self._verify_telegram_data(payload)
        return await self._get_or_create_telegram_session(
            telegram_id=str(telegram_data["id"]),
            first_name=telegram_data.get("first_name", ""),
            last_name=telegram_data.get("last_name", ""),
            username=telegram_data.get("username"),
            request=request,
        )

    def _verify_telegram_webapp_init_data(self, init_data: str) -> dict:
        """Telegram MINI APP flow (web3.enwis.uz opened inside Telegram) —
        verifies `Telegram.WebApp.initData` per Telegram's Mini Apps spec.
        secret_key = HMAC-SHA256(key="WebAppData", msg=bot_token), then
        hash = HMAC-SHA256(key=secret_key, msg=data_check_string).
        """
        import json
        from urllib.parse import unquote

        logger.warning(f"RAW init_data={init_data!r}")

        # Qo'lda parse qilamiz — parse_qsl() ichida unquote_plus ishlatadi,
        # ya'ni "+" belgisini bo'sh joyga aylantiradi va JSON ichidagi "+"
        # (masalan photo_url'dagi maxsus belgilarda) buzilishi mumkin.
        pairs = {}
        for part in init_data.split("&"):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            pairs[unquote(k)] = unquote(v)

        received_hash = pairs.pop("hash", None)
        if not received_hash:
            raise HTTPException(401, "Missing initData hash")

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(pairs.items())
        )
        secret_key = hmac.new(
            b"WebAppData", settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256
        ).digest()
        calculated_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        logger.warning(f"pairs={pairs!r}")
        logger.warning(f"data_check_string={data_check_string!r}")
        logger.warning(f"calculated={calculated_hash} received={received_hash}")

        if not hmac.compare_digest(calculated_hash, received_hash):
            raise HTTPException(401, "Invalid Telegram WebApp signature")

        auth_date = int(pairs.get("auth_date", 0))
        if self._now().timestamp() - auth_date > 86400:
            raise HTTPException(401, "initData has expired — reopen the Mini App")

        user_json = pairs.get("user")
        if not user_json:
            raise HTTPException(401, "initData missing user field")
        return json.loads(user_json)

    async def telegram_webapp_auth(self, init_data: str, request: Request) -> dict:
        """Login/register via a Telegram Mini App's initData — the ONLY
        auth path for web3.enwis.uz. No password, no separate register
        step: opening the Mini App IS the login."""
        tg_user = self._verify_telegram_webapp_init_data(init_data)
        return await self._get_or_create_telegram_session(
            telegram_id=str(tg_user["id"]),
            first_name=tg_user.get("first_name", ""),
            last_name=tg_user.get("last_name", ""),
            username=tg_user.get("username"),
            request=request,
        )

    async def _get_or_create_telegram_session(
        self,
        telegram_id: str,
        first_name: str,
        last_name: str,
        username: str | None,
        request: Request,
    ) -> dict:
        result = await self.db.execute(
            select(SocialAccount)
            .options(selectinload(SocialAccount.user).selectinload(User.roles))
            .where(
                SocialAccount.provider == AuthProvider.TELEGRAM,
                SocialAccount.provider_id == telegram_id,
            )
        )
        account = result.scalar_one_or_none()
        if account:
            user = account.user
            if not user.is_telegram_verified:
                user.is_telegram_verified = True
                await self.db.commit()
            return await self._create_session(user, request)

        full_name = f"{first_name}&nbsp;{last_name}".strip() or None
        user = User(
            username=await self._generate_unique_username(username),
            full_name=full_name,
            telegram_id=telegram_id,
            is_telegram_verified=True,
            is_verified=True,
            status=UserStatus.ACTIVE,
            is_active=True,
        )
        if user.full_name:
            user.full_name = user.full_name.replace("&nbsp;", " ")

        self.db.add(user)
        await self.db.flush()
        await self._attach_default_role(user)
        self.db.add(
            SocialAccount(
                user_id=user.id,
                provider=AuthProvider.TELEGRAM,
                provider_id=telegram_id,
            )
        )
        await self.db.commit()
        return await self._create_session(user, request)

    async def link_google(self, user: User, id_token_str: str) -> dict:
        google_data = self._verify_google_token(id_token_str)
        provider_id = google_data["sub"]
        email = google_data.get("email", "").lower() or None
        existing = await self.db.execute(
            select(SocialAccount).where(
                SocialAccount.provider == AuthProvider.GOOGLE,
                SocialAccount.provider_id == provider_id,
            )
        )
        account = existing.scalar_one_or_none()
        if account and account.user_id != user.id:
            raise HTTPException(409, "This Google account is already linked")
        if account and account.user_id == user.id:
            return {"provider": "google", "linked": True, "email": account.email}
        self.db.add(
            SocialAccount(
                user_id=user.id,
                provider=AuthProvider.GOOGLE,
                provider_id=provider_id,
                email=email,
                email_verified=google_data.get("email_verified", False),
            )
        )
        if not user.google_id:
            user.google_id = provider_id
            user.is_google_verified = True
        await self.db.commit()
        return {"provider": "google", "linked": True, "email": email}

    async def unlink_google(self, user: User) -> dict:
        await self._unlink_provider(user, AuthProvider.GOOGLE)
        user.google_id = None
        await self.db.commit()
        return {"provider": "google", "linked": False, "email": None}

    async def link_telegram(self, user: User, telegram_data: dict) -> dict:
        verified = self._verify_telegram_data(telegram_data)
        telegram_id = str(verified["id"])
        existing = await self.db.execute(
            select(SocialAccount).where(
                SocialAccount.provider == AuthProvider.TELEGRAM,
                SocialAccount.provider_id == telegram_id,
            )
        )
        account = existing.scalar_one_or_none()
        if account and account.user_id != user.id:
            raise HTTPException(409, "This Telegram account is already linked")
        if account and account.user_id == user.id:
            return {"provider": "telegram", "linked": True}
        self.db.add(
            SocialAccount(
                user_id=user.id,
                provider=AuthProvider.TELEGRAM,
                provider_id=telegram_id,
            )
        )
        if not user.telegram_id:
            user.telegram_id = telegram_id
            user.is_telegram_verified = True
        await self.db.commit()
        return {"provider": "telegram", "linked": True}
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
        await self.db.execute(
            delete(SocialAccount).where(SocialAccount.id == account.id)
        )
