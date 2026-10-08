from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.exams.certificate_service import CertificateService


async def get_certificate_service(db: AsyncSession = Depends(get_db)) -> CertificateService:
    return CertificateService(db)
