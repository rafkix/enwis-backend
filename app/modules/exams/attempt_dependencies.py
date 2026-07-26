from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.exams.attempt_service import AttemptService


def get_attempt_service(db: AsyncSession = Depends(get_db)) -> AttemptService:
    return AttemptService(db)
