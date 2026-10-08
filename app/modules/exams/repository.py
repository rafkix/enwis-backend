import math
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.exams.models import Exam, ExamParticipant


class ExamRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, exam_id: uuid.UUID) -> Exam | None:
        result = await self.db.execute(
            select(Exam)
            .options(
                selectinload(Exam.test),
                selectinload(Exam.attempts),
            )
            .where(Exam.id == exam_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_owner(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Exam | None:
        result = await self.db.execute(
            select(Exam)
            .options(
                selectinload(Exam.test),
                selectinload(Exam.attempts),
            )
            .where(Exam.id == exam_id, Exam.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def count_by_owner(self, owner_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(Exam.id)).where(Exam.owner_id == owner_id)
        )
        return result.scalar_one() or 0

    async def list_by_owner(
        self,
        owner_id: uuid.UUID,
        page: int = 1,
        per_page: int = 20,
        status_filter: str | None = None,
        search: str | None = None,
    ) -> dict:
        q = select(Exam).where(Exam.owner_id == owner_id)
        count_q = select(func.count(Exam.id)).where(
            Exam.owner_id == owner_id
        )

        if status_filter:
            q = q.where(Exam.status == status_filter)
            count_q = count_q.where(Exam.status == status_filter)
        if search:
            q = q.where(Exam.title.ilike(f"%{search}%"))
            count_q = count_q.where(Exam.title.ilike(f"%{search}%"))

        total = (await self.db.execute(count_q)).scalar_one()

        result = await self.db.execute(
            q.options(selectinload(Exam.test), selectinload(Exam.attempts))
            .order_by(Exam.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        exams = list(result.scalars().all())

        items = []
        for exam in exams:
            test = exam.test
            questions_count = 0
            if test and hasattr(test, "test_questions"):
                questions_count = len(test.test_questions)

            items.append({
                "id": exam.id,
                "title": exam.title,
                "test_id": exam.test_id,
                "test_title": test.title if test else None,
                "status": (
                    exam.status.value
                    if hasattr(exam.status, "value")
                    else exam.status
                ),
                "visibility": (
                    exam.visibility.value
                    if hasattr(exam.visibility, "value")
                    else exam.visibility
                ),
                "start_time": exam.start_time,
                "end_time": exam.end_time,
                "questions_count": questions_count,
                "attempts_count": len(exam.attempts),
                "avg_score": 0.0,
                "created_at": exam.created_at,
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total > 0 else 1,
        }


class ExamParticipantRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(
        self, exam_id: uuid.UUID, user_id: uuid.UUID
    ) -> ExamParticipant:
        participant = ExamParticipant(exam_id=exam_id, user_id=user_id)
        self.db.add(participant)
        await self.db.flush()
        await self.db.refresh(participant)
        return participant

    async def list_by_exam(
        self, exam_id: uuid.UUID
    ) -> list[ExamParticipant]:
        result = await self.db.execute(
            select(ExamParticipant)
            .options(selectinload(ExamParticipant.user))
            .where(ExamParticipant.exam_id == exam_id)
            .order_by(ExamParticipant.created_at.desc())
        )
        return list(result.scalars().all())

    async def remove(
        self, exam_id: uuid.UUID, participant_id: uuid.UUID
    ) -> None:
        result = await self.db.execute(
            select(ExamParticipant).where(
                ExamParticipant.id == participant_id,
                ExamParticipant.exam_id == exam_id,
            )
        )
        p = result.scalar_one_or_none()
        if p:
            await self.db.delete(p)
            await self.db.flush()

    async def count_by_exam(self, exam_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(ExamParticipant.id)).where(
                ExamParticipant.exam_id == exam_id
            )
        )
        return result.scalar_one() or 0
