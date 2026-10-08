import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.exams.models import Exam, ExamAttempt, ExamStatus, QuestionAnswer
from app.modules.questions.models import Question as QBQuestion
from app.modules.tests.models import Test, TestQuestion


class AttemptRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _load_exam_with_questions(self, exam_id: uuid.UUID) -> Exam | None:
        result = await self.db.execute(
            select(Exam)
            .options(
                selectinload(Exam.test)
                .selectinload(Test.test_questions)
                .selectinload(TestQuestion.question)
                .selectinload(QBQuestion.choices),
            )
            .where(Exam.id == exam_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_exam_by_id(self, exam_id: uuid.UUID) -> Exam | None:
        return await self._load_exam_with_questions(exam_id)

    async def get_active_exam(self, exam_id: uuid.UUID) -> Exam | None:
        result = await self.db.execute(
            select(Exam)
            .options(
                selectinload(Exam.test)
                .selectinload(Test.test_questions)
                .selectinload(TestQuestion.question)
                .selectinload(QBQuestion.choices),
            )
            .where(Exam.id == exam_id, Exam.status == ExamStatus.ACTIVE)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def count_user_attempts(self, exam_id: uuid.UUID, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(ExamAttempt.id)).where(
                ExamAttempt.exam_id == exam_id,
                ExamAttempt.user_id == user_id,
            )
        )
        return result.scalar_one() or 0

    async def get_active_attempt(
        self, exam_id: uuid.UUID, user_id: uuid.UUID
    ) -> ExamAttempt | None:
        result = await self.db.execute(
            select(ExamAttempt).where(
                ExamAttempt.exam_id == exam_id,
                ExamAttempt.user_id == user_id,
                ExamAttempt.is_completed.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def create_attempt(
        self, exam_id: uuid.UUID, user_id: uuid.UUID, total_points: int
    ) -> ExamAttempt:
        attempt = ExamAttempt(
            exam_id=exam_id,
            user_id=user_id,
            total_points=total_points,
            is_completed=False,
            started_at=datetime.now(UTC),
        )
        self.db.add(attempt)
        await self.db.flush()
        await self.db.refresh(attempt)
        return attempt

    async def get_attempt_by_id(self, attempt_id: uuid.UUID) -> ExamAttempt | None:
        result = await self.db.execute(
            select(ExamAttempt)
            .options(selectinload(ExamAttempt.answers))
            .where(ExamAttempt.id == attempt_id)
        )
        return result.scalar_one_or_none()

    async def get_attempt_with_relations(
        self, attempt_id: uuid.UUID
    ) -> ExamAttempt | None:
        result = await self.db.execute(
            select(ExamAttempt)
            .options(
                selectinload(ExamAttempt.answers),
                selectinload(ExamAttempt.exam)
                .selectinload(Exam.test)
                .selectinload(Test.test_questions)
                .selectinload(TestQuestion.question)
                .selectinload(QBQuestion.choices),
            )
            .where(ExamAttempt.id == attempt_id)
        )
        return result.scalar_one_or_none()

    async def get_user_attempt(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID
    ) -> ExamAttempt | None:
        result = await self.db.execute(
            select(ExamAttempt)
            .options(selectinload(ExamAttempt.answers))
            .where(ExamAttempt.id == attempt_id, ExamAttempt.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def save_answers(self, answers: list[QuestionAnswer]) -> None:
        self.db.add_all(answers)
        await self.db.flush()

    async def get_existing_answer(
        self, attempt_id: uuid.UUID, question_id: uuid.UUID
    ) -> QuestionAnswer | None:
        result = await self.db.execute(
            select(QuestionAnswer).where(
                QuestionAnswer.attempt_id == attempt_id,
                QuestionAnswer.question_id == question_id,
            )
        )
        return result.scalar_one_or_none()

    async def delete_existing_answer(self, answer: QuestionAnswer) -> None:
        await self.db.delete(answer)
        await self.db.flush()

    async def delete_answers_for_questions(
        self, attempt_id: uuid.UUID, question_ids: list[uuid.UUID]
    ) -> None:
        if not question_ids:
            return
        await self.db.execute(
            delete(QuestionAnswer).where(
                QuestionAnswer.attempt_id == attempt_id,
                QuestionAnswer.question_id.in_(question_ids),
            )
        )
        await self.db.flush()


    async def complete_attempt(self, attempt_id: uuid.UUID, score: int) -> ExamAttempt:
        now = datetime.now(UTC)
        await self.db.execute(
            update(ExamAttempt)
            .where(ExamAttempt.id == attempt_id)
            .values(is_completed=True, score=score, completed_at=now)
        )
        await self.db.flush()
        return await self.get_attempt_by_id(attempt_id)

    async def get_attempts_for_exam(
        self, exam_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> dict:
        base = select(ExamAttempt).where(ExamAttempt.exam_id == exam_id)

        total_q = select(func.count(ExamAttempt.id)).where(
            ExamAttempt.exam_id == exam_id
        )
        total = (await self.db.execute(total_q)).scalar_one() or 0

        result = await self.db.execute(
            base.order_by(ExamAttempt.started_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        items = result.scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total else 1,
        }

    async def get_attempts_for_user(
        self, user_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> dict:
        base = (
            select(ExamAttempt)
            .options(selectinload(ExamAttempt.exam))
            .where(ExamAttempt.user_id == user_id)
        )

        total_q = select(func.count(ExamAttempt.id)).where(
            ExamAttempt.user_id == user_id
        )
        total = (await self.db.execute(total_q)).scalar_one() or 0

        result = await self.db.execute(
            base.order_by(ExamAttempt.started_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        items = result.scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total else 1,
        }

    async def get_leaderboard(self, exam_id: uuid.UUID, limit: int = 50) -> list:
        result = await self.db.execute(
            select(ExamAttempt)
            .where(
                ExamAttempt.exam_id == exam_id,
                ExamAttempt.is_completed.is_(True),
            )
            .order_by(ExamAttempt.score.desc().nullslast())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_all_completed_for_exam(self, exam_id: uuid.UUID) -> list:
        result = await self.db.execute(
            select(ExamAttempt).where(
                ExamAttempt.exam_id == exam_id,
                ExamAttempt.is_completed.is_(True),
            )
        )
        return list(result.scalars().all())

    async def get_answers_for_attempt(self, attempt_id: uuid.UUID) -> list:
        result = await self.db.execute(
            select(QuestionAnswer).where(QuestionAnswer.attempt_id == attempt_id)
        )
        return list(result.scalars().all())
