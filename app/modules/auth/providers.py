"""Eskiz.uz SMS provider — async implementation."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class AbstractSMSProvider(ABC):
    """Interface every SMS gateway adapter must implement."""

    @abstractmethod
    async def send_otp(self, phone_number: str, code: str) -> None:
        """Deliver the one-time *code* to *phone_number*."""
        ...


class ConsoleSMSProvider(AbstractSMSProvider):
    """Logs OTP to the console — safe for development / testing."""

    async def send_otp(self, phone_number: str, code: str) -> None:
        logger.info("📱 SMS [%s] → OTP code: %s", phone_number, code)


class EskizSMSProvider(AbstractSMSProvider):
    """Send OTP codes via Eskiz.uz SMS gateway.

    Token is cached for ~23 hours to avoid repeated logins.
    """

    LOGIN_URL = "https://notify.eskiz.uz/api/auth/login"
    SMS_URL = "https://notify.eskiz.uz/api/message/sms/send"

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone to 12-digit format: 998XXXXXXXXX."""
        phone = phone.strip()
        if phone.startswith("+"):
            phone = phone[1:]
        phone = re.sub(r"\D", "", phone)
        if not phone.startswith("998") or len(phone) != 12:
            raise ValueError(
                f"Invalid phone format: {phone}. Expected: 998901234567"
            )
        return phone

    async def _get_token(self) -> str:
        """Get or refresh Eskiz API token."""
        if (
            self._token
            and self._token_expires_at
            and self._token_expires_at > datetime.now(UTC)
        ):
            return self._token

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.LOGIN_URL,
                data={
                    "email": settings.ESKIZ_EMAIL,
                    "password": settings.ESKIZ_PASSWORD,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        logger.info("Eskiz login status: %s", response.status_code)

        if response.status_code != 200:
            logger.error("Eskiz login failed: %s", response.text)
            raise Exception(f"Eskiz login failed: {response.status_code}")

        data = response.json()
        token = data.get("data", {}).get("token")

        if not token:
            raise Exception("Eskiz token not found")

        self._token = token
        self._token_expires_at = datetime.now(UTC) + timedelta(hours=23)

        logger.info("Eskiz token refreshed")
        return self._token

    async def send_otp(self, phone_number: str, code: str) -> None:
        """Send OTP code via Eskiz SMS gateway."""
        phone = self._normalize_phone(phone_number)

        message = f"NarxNav sayti orqali ro\'yxatdan o\'tish uchun tasdiqlash kodingiz: {code}"

        if len(message) > 160:
            raise ValueError("SMS exceeds 160 characters")

        token = await self._get_token()

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.SMS_URL,
                json={
                    "mobile_phone": phone,
                    "message": message,
                    "from": settings.SMS_FROM,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                },
            )

        logger.info("Eskiz SMS status: %s", response.status_code)

        if response.status_code != 200:
            logger.error("Eskiz SMS xato: %s", response.text)
            raise Exception(f"SMS yuborishda xato: {response.text}")

        logger.info("SMS yuborildi: %s → %s", code, phone)
