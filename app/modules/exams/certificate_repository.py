import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.exams.models import Certificate


class CertificateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, certificate_id: uuid.UUID) -> Certificate | None:
        result = await self.db.execute(
            select(Certificate)
            .options(selectinload(Certificate.exam), selectinload(Certificate.user))
            .where(Certificate.id == certificate_id)
        )
        return result.scalar_one_or_none()

    async def get_by_serial(self, serial_number: str) -> Certificate | None:
        result = await self.db.execute(
            select(Certificate)
            .options(selectinload(Certificate.exam), selectinload(Certificate.user))
            .where(Certificate.serial_number == serial_number)
        )
        return result.scalar_one_or_none()

    async def get_by_attempt(self, attempt_id: uuid.UUID) -> Certificate | None:
        result = await self.db.execute(
            select(Certificate).where(Certificate.attempt_id == attempt_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Certificate]:
        result = await self.db.execute(
            select(Certificate)
            .options(selectinload(Certificate.exam))
            .where(Certificate.user_id == user_id, Certificate.revoked_at.is_(None))
            .order_by(Certificate.issued_at.desc())
        )
        return list(result.scalars().all())

    async def serial_exists(self, serial_number: str) -> bool:
        result = await self.db.execute(
            select(Certificate.id).where(Certificate.serial_number == serial_number)
        )
        return result.scalar_one_or_none() is not None

    def add(self, certificate: Certificate) -> None:
        self.db.add(certificate)
