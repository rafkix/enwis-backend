import hashlib
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import PlanTier, get_ai_monthly_limit, get_plan_features, get_user_plan_tier
from app.core.security import hash_password, verify_password
from app.modules.auth.models import PhoneVerification, Session, User
from app.modules.auth.providers import ConsoleSMSProvider, EskizSMSProvider
from app.modules.users.constants import (
    ALLOWED_AVATAR_MIMES as ALLOWED_MIME_TYPES,
)
from app.modules.users.constants import (
    MAX_AVATAR_SIZE,
    OTP_EXPIRE_MINUTES,
    OTP_MAX_ATTEMPTS,
    UPLOAD_DIR,
)
from app.modules.users.schemas import (
    AccountSummary,
    DeviceResponse,
    PlanInfo,
    ReferralSummary,
    SessionResponse,
    UserMeta,
    UserResponse,
)

logger = logging.getLogger(__name__)


async def _send_sms(phone: str, code: str) -> None:
    try:
        provider = EskizSMSProvider() if settings.ESKIZ_EMAIL else ConsoleSMSProvider()
        await provider.send_otp(phone, code)
    except Exception as exc:
        logger.error("Failed to send SMS to %s: %s", phone, exc)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _now(self) -> datetime:
        return datetime.utcnow()

    def _deep_merge(self, base: dict, incoming: dict) -> dict:
        result = base.copy()
        for k, v in incoming.items():
            if v is None:
                continue
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def _serialize_user(self, user: User) -> UserResponse:
        meta = None
        if user.meta:
            try:
                meta = UserMeta.model_validate(user.meta)
            except Exception as e:
                logger.warning("UserMeta parse error (user_id=%s): %s", user.id, e)

        is_teacher = any(r.name.upper() == "TEACHER" for r in (user.roles or []))

        sub_tier = getattr(user, "subscription_tier", "FREE") or "FREE"
        sub_expires = getattr(user, "subscription_tier_expires_at", None)
        has_active_sub = False
        sub_status = None
        if sub_tier and sub_tier.upper() != "FREE":
            if sub_expires and sub_expires > self._now():
                has_active_sub = True
                sub_status = "active"
            elif sub_expires:
                sub_status = "expired"
            else:
                has_active_sub = True
                sub_status = "active"

        # Google/Telegram orqali ro'yxatdan o'tgan foydalanuvchilar parolsiz
        # va telefonsiz keladi. Endi bunday hollarda parol o'rnatish haqida
        # bezovta qilmaymiz — buning o'rniga telefonni tasdiqlashni talab
        # qilamiz (frontend shu flagga qarab tegishli bannerni ko'rsatadi).
        signed_up_via_social = bool(user.is_google_verified or user.is_telegram_verified)
        requires_phone_verification = signed_up_via_social and not user.phone_verified
        requires_password_setup = (not bool(user.password_hash)) and not signed_up_via_social

        return UserResponse(
            id=user.id,
            public_id=user.public_id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            phone=user.phone,
            phone_verified=user.phone_verified,
            avatar=user.avatar,
            is_google_verified=user.is_google_verified,
            is_telegram_verified=user.is_telegram_verified,
            is_verified=user.is_verified,
            is_active=user.is_active,
            status=user.status.value,
            roles=[r.name for r in user.roles] if user.roles else [],
            meta=meta,
            has_password=bool(user.password_hash),
            requires_phone_verification=requires_phone_verification,
            requires_password_setup=requires_password_setup,
            referral_code=getattr(user, "referral_code", None),
            xp=getattr(user, "xp", 0),
            level=getattr(user, "level", 1),
            streak=getattr(user, "streak", 0),
            is_teacher=is_teacher,
            teacher_verified_at=getattr(user, "teacher_verified_at", None),
            subscription_tier=sub_tier,
            subscription_status=sub_status,
            subscription_expires_at=sub_expires,
            has_active_subscription=has_active_sub,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    async def _ensure_referral_code(self, user: User) -> str:
        if user.referral_code:
            return user.referral_code
        while True:
            candidate = (
                secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
            )
            existing = await self.db.execute(
                select(User.id).where(User.referral_code == candidate)
            )
            if not existing.scalar_one_or_none():
                user.referral_code = candidate
                await self.db.commit()
                await self.db.refresh(user)
                return candidate

    async def get_profile(self, user: User) -> UserResponse:
        return self._serialize_user(user)

    async def get_referral_summary(self, user: User) -> dict:
        code = await self._ensure_referral_code(user)
        count_res = await self.db.execute(
            select(User.id).where(User.referred_by_id == user.id)
        )
        invited_count = len(count_res.scalars().all())
        return {
            "referral_code": code,
            "invited_count": invited_count,
            "referral_url": f"/register?ref={code}",
        }

    async def update_profile(self, user: User, data) -> dict:
        if data.username is not None:
            cleaned = data.username.strip().lower()
            if not re.match(r"^[a-zA-Z0-9._]{3,30}$", cleaned):
                raise HTTPException(400, "Username must be 3-30 characters and contain only letters, numbers, underscores, and dots")
            res = await self.db.execute(
                select(User).where(User.username == cleaned, User.id != user.id)
            )
            if res.scalar_one_or_none():
                raise HTTPException(400, "Username already taken")
            user.username = cleaned

        if data.full_name is not None:
            cleaned = data.full_name.strip()
            if len(cleaned) < 2 or len(cleaned) > 255:
                raise HTTPException(400, "Full name must be between 2 and 255 characters")
            user.full_name = cleaned

        if data.email is not None:
            cleaned = data.email.strip().lower()
            if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", cleaned):
                raise HTTPException(400, "Invalid email format")
            res = await self.db.execute(
                select(User).where(User.email == cleaned, User.id != user.id)
            )
            if res.scalar_one_or_none():
                raise HTTPException(400, "Email already in use")
            user.email = cleaned

        if data.phone is not None:
            cleaned = re.sub(r"[\s\-\(\)]", "", data.phone.strip())
            if not re.match(r"^\+?[0-9]{7,15}$", cleaned):
                raise HTTPException(400, "Invalid phone number format")
            res = await self.db.execute(
                select(User).where(User.phone == cleaned, User.id != user.id)
            )
            if res.scalar_one_or_none():
                raise HTTPException(400, "Phone number already in use")
            user.phone = cleaned

        if data.meta is not None:
            current_meta: dict = {}
            if user.meta:
                if isinstance(user.meta, dict):
                    current_meta = user.meta
                else:
                    try:
                        current_meta = user.meta.model_dump()
                    except Exception:
                        current_meta = {}
            incoming = data.meta.model_dump(exclude_none=True)
            merged = self._deep_merge(current_meta, incoming)
            merged.setdefault("version", 1)
            user.meta = merged

        await self.db.commit()
        await self.db.refresh(user)
        return {"user": self._serialize_user(user), "message": "Profile updated"}

    async def update_avatar(self, user: User, avatar: UploadFile) -> dict:
        if avatar.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                400, "File type not allowed. Accepted: jpeg, png, webp"
            )

        content = await avatar.read()
        if len(content) > MAX_AVATAR_SIZE:
            raise HTTPException(400, "File size must not exceed 2MB")

        ext = (avatar.filename or "image").rsplit(".", 1)[-1].lower()
        if ext not in {"jpg", "jpeg", "png", "webp"}:
            ext = "jpg"

        filename = f"{uuid.uuid4()}.{ext}"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_path = os.path.join(UPLOAD_DIR, filename)
        with open(file_path, "wb") as f:
            f.write(content)

        if user.avatar and user.avatar.startswith("/static/avatars/"):
            old_path = user.avatar.lstrip("/")
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except OSError as e:
                    logger.warning("Old avatar could not be deleted: %s", e)
        user.avatar = f"/static/avatars/{filename}"
        await self.db.commit()
        await self.db.refresh(user)

        return {
            "success": True,
            "avatar": user.avatar,
            "message": "Avatar updated",
        }

    async def confirm_avatar_url(self, user: User, avatar_url: str) -> dict:
        if not re.match(r"^https?://", avatar_url):
            raise HTTPException(400, "Invalid avatar URL")
        user.avatar = avatar_url
        await self.db.commit()
        await self.db.refresh(user)
        return {"success": True, "avatar": user.avatar, "message": "Avatar updated"}

    async def change_password(self, user: User, current_password: str, new_password: str) -> dict:
        if not user.password_hash:
            raise HTTPException(400, "No password set. Use set_password first.")
        valid, _ = verify_password(current_password, user.password_hash)
        if not valid:
            raise HTTPException(400, "Current password is incorrect")
        user.password_hash = hash_password(new_password)
        await self.db.commit()
        return {"success": True, "message": "Password changed"}

    async def set_password(self, user: User, new_password: str) -> dict:
        if user.password_hash:
            raise HTTPException(400, "Password already set. Use change_password instead.")
        user.password_hash = hash_password(new_password)
        await self.db.commit()
        return {"success": True, "message": "Password set"}

    async def delete_account(self, user: User, password: str | None = None) -> dict:
        if user.password_hash:
            if not password:
                raise HTTPException(400, "Password required to delete account")
            valid, _ = verify_password(password, user.password_hash)
            if not valid:
                raise HTTPException(400, "Incorrect password")
        await self.db.delete(user)
        await self.db.commit()
        return {"success": True, "message": "Account deleted"}

    async def get_devices(self, user: User) -> list:
        res = await self.db.execute(
            select(Session)
            .where(
                Session.user_id == user.id,
                Session.is_revoked.is_(False),
                Session.expires_at > self._now(),
            )
            .order_by(Session.created_at.desc())
        )
        return res.scalars().all()

    async def revoke_device(self, user: User, session_id: str) -> dict:
        res = await self.db.execute(
            select(Session).where(
                Session.id == uuid.UUID(session_id),
                Session.user_id == user.id,
            )
        )
        session = res.scalar_one_or_none()
        if not session:
            raise HTTPException(404, "Session not found")
        session.is_revoked = True
        await self.db.commit()
        return {"success": True, "message": "Device logged out"}

    async def revoke_other_devices(self, user: User, current_session_id: str) -> dict:
        await self.db.execute(
            update(Session)
            .where(
                Session.user_id == user.id,
                Session.id != current_session_id,
            )
            .values(is_revoked=True)
        )
        await self.db.commit()
        return {"success": True, "message": "Other devices logged out"}

    async def get_sessions(self, user: User, current_session_id: str | None = None) -> list:
        res = await self.db.execute(
            select(Session)
            .where(
                Session.user_id == user.id,
                Session.is_revoked.is_(False),
                Session.expires_at > self._now(),
            )
            .order_by(Session.created_at.desc())
        )
        sessions = res.scalars().all()
        return [
            SessionResponse(
                id=s.id,
                ip_address=s.ip_address,
                user_agent=s.user_agent,
                device_name=s.device_name,
                is_revoked=s.is_revoked,
                is_current=str(s.id) == str(current_session_id) if current_session_id else False,
                expires_at=s.expires_at,
                last_used_at=s.last_used_at,
                created_at=s.created_at,
            )
            for s in sessions
        ]

    async def get_account_summary(self, user: User, current_session_id: str | None = None) -> dict:
        profile = self._serialize_user(user)
        sessions = await self.get_sessions(user, current_session_id)
        devices_list = await self.get_devices(user)

        code = await self._ensure_referral_code(user)
        count_res = await self.db.execute(
            select(User.id).where(User.referred_by_id == user.id)
        )
        invited_count = len(count_res.scalars().all())

        settings = {}
        if user.meta and isinstance(user.meta, dict):
            setting_keys = (
                "language", "timezone", "email_notifications",
                "sms_notifications", "push_notifications", "marketing_consent",
            )
            settings = {k: user.meta.get(k) for k in setting_keys if k in user.meta}

        tier = get_user_plan_tier(user.subscription_tier)
        plan_features = get_plan_features(tier)
        expires_at = user.subscription_tier_expires_at
        status = "active"
        if expires_at and expires_at < self._now():
            status = "expired"
            tier = PlanTier.FREE
            plan_features = get_plan_features(tier)

        return AccountSummary(
            user=profile,
            sessions=sessions,
            devices=[DeviceResponse.model_validate(d) for d in devices_list],
            plan=PlanInfo(
                tier=tier.value,
                status=status,
                expires_at=expires_at,
                features=plan_features["features"],
                ai_questions_used=getattr(user, "ai_questions_used", 0) or 0,
                ai_questions_monthly_limit=get_ai_monthly_limit(tier),
                ai_questions_reset_at=getattr(user, "ai_questions_reset_at", None),
            ),
            referral=ReferralSummary(
                referral_code=code,
                invited_count=invited_count,
                referral_url=f"/register?ref={code}",
            ),
            settings=settings,
        ).model_dump()

    async def update_settings(self, user: User, data) -> dict:
        if not user.meta or not isinstance(user.meta, dict):
            user.meta = {}
        changed = []
        updates = data.model_dump(exclude_none=True)
        for k, v in updates.items():
            if hasattr(user, k):
                setattr(user, k, v)
                changed.append(k)
            else:
                user.meta[k] = v
                changed.append(k)
        if changed:
            await self.db.commit()
            await self.db.refresh(user)
        return {"success": True, "message": "Settings updated", "changed": changed}

    async def request_phone_update(self, user: User, phone: str) -> dict:
        res = await self.db.execute(
            select(User).where(User.phone == phone, User.id != user.id)
        )
        if res.scalar_one_or_none():
            raise HTTPException(400, "This phone number is already in use")

        await self.db.execute(
            update(PhoneVerification)
            .where(
                PhoneVerification.user_id == user.id,
                PhoneVerification.is_used.is_(False),
            )
            .values(is_used=True)
        )

        code = str(secrets.randbelow(900000) + 100000)
        expires_at = self._now() + timedelta(minutes=OTP_EXPIRE_MINUTES)

        verification = PhoneVerification(
            user_id=user.id,
            phone=phone,
            code_hash=_hash_code(code),
            expires_at=expires_at,
        )
        self.db.add(verification)
        await self.db.commit()

        await _send_sms(phone, code)

        return {
            "success": True,
            "message": f"SMS sent. Code expires in {OTP_EXPIRE_MINUTES} minutes.",
            "expires_in": OTP_EXPIRE_MINUTES * 60,
        }

    async def verify_phone_update(self, user: User, phone: str, code: str) -> dict:
        res = await self.db.execute(
            select(PhoneVerification)
            .where(
                PhoneVerification.user_id == user.id,
                PhoneVerification.phone == phone,
                PhoneVerification.is_used.is_(False),
            )
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
        verification = res.scalar_one_or_none()

        if not verification:
            raise HTTPException(400, "No active verification found. Please request again.")

        if self._now() > verification.expires_at:
            verification.is_used = True
            await self.db.commit()
            raise HTTPException(400, "Code has expired. Please request again.")

        if verification.attempts >= OTP_MAX_ATTEMPTS:
            verification.is_used = True
            await self.db.commit()
            raise HTTPException(
                429,
                f"Too many incorrect attempts ({OTP_MAX_ATTEMPTS}). Please request again.",
            )

        verification.attempts += 1

        if verification.code_hash != _hash_code(code):
            await self.db.commit()
            remaining = OTP_MAX_ATTEMPTS - verification.attempts
            raise HTTPException(400, f"Incorrect code. Remaining attempts: {remaining}")

        verification.is_used = True
        user.phone = phone
        user.phone_verified = True

        await self.db.commit()
        await self.db.refresh(user)

        return {
            "success": True,
            "message": "Phone number verified",
            "phone": user.phone,
        }
