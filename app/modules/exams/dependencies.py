from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.exams.service import ExamService


async def get_exam_service(db: AsyncSession = Depends(get_db)) -> ExamService:
    return ExamService(db)
