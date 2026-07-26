import logging
import math
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.plans import (
    PlanTier,
    check_participant_limit,
    check_test_limit,
    get_plan_limits,
    get_user_plan_tier,
)
from app.modules.exams.exceptions import (
    ExamLimitExceededException,
    ExamNotFoundException,
    ParticipantLimitExceededException,
)
from app.modules.exams.models import (
    Exam,
    ExamAttempt,
    ExamParticipant,
    ExamStatus,
    QuestionAnswer,
)
from app.modules.exams.repository import (
    ExamParticipantRepository,
    ExamRepository,
)
from app.modules.questions.models import Question as QBQuestion
from app.modules.tests.models import Test, TestQuestion

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

logger = logging.getLogger(__name__)


class ExamService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ExamRepository(db)
        self.participant_repo = ExamParticipantRepository(db)

    def _now(self) -> datetime:
        return datetime.now(UTC)

    async def _get_user_tier(self, user_id: uuid.UUID) -> PlanTier:
        from app.modules.auth.models import User

        result = await self.db.execute(
            select(User.subscription_tier).where(User.id == user_id)
        )
        tier_str = result.scalar_one_or_none()
        return get_user_plan_tier(tier_str)

    async def _check_exam_quota(self, owner_id: uuid.UUID) -> None:
        tier = await self._get_user_tier(owner_id)
        limits = get_plan_limits(tier)
        if limits.max_tests is None or limits.max_tests == -1:
            return
        current_count = await self.repo.count_by_owner(owner_id)
        if not check_test_limit(current_count, tier):
            raise ExamLimitExceededException(limits.max_tests, tier.value)

    async def _check_participant_quota(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID
    ) -> None:
        tier = await self._get_user_tier(owner_id)
        limits = get_plan_limits(tier)
        if (
            limits.max_participants_per_test is None
            or limits.max_participants_per_test == -1
        ):
            return
        current_count = await self.participant_repo.count_by_exam(exam_id)
        if not check_participant_limit(current_count, tier):
            raise ParticipantLimitExceededException(
                limits.max_participants_per_test, tier.value
            )

    async def _get_linked_test(
        self, test_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Test:
        result = await self.db.execute(
            select(Test)
            .options(
                selectinload(Test.test_questions).selectinload(
                    TestQuestion.test
                )
            )
            .where(Test.id == test_id, Test.owner_id == owner_id)
        )
        test = result.scalar_one_or_none()
        if not test:
            raise HTTPException(404, "Linked test not found")
        return test

    # ── Exam CRUD ─────────────────────────────────────────────────────

    async def list_exams(
        self,
        owner_id: uuid.UUID,
        page: int = 1,
        per_page: int = 20,
        status_filter: str | None = None,
        search: str | None = None,
    ) -> dict:
        return await self.repo.list_by_owner(
            owner_id, page, per_page, status_filter, search
        )

    async def get_exam(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Exam:
        exam = await self.repo.get_by_id_owner(exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()
        return exam

    async def create_exam(
        self, data: dict, owner_id: uuid.UUID
    ) -> Exam:
        await self._check_exam_quota(owner_id)

        test_id = data.pop("test_id")
        await self._get_linked_test(test_id, owner_id)

        password = data.pop("password", None)
        password_hash = None
        if password:
            password_hash = pwd_context.hash(password)

        exam = Exam(
            title=data["title"],
            description=data.get("description"),
            test_id=test_id,
            visibility=data.get("visibility", "private"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            duration_minutes=data.get("duration_minutes"),
            passing_score=data.get("passing_score", 60),
            max_attempts=data.get("max_attempts", 3),
            password_hash=password_hash,
            owner_id=owner_id,
            status=ExamStatus.DRAFT,
        )
        self.db.add(exam)
        await self.db.flush()
        await self.db.refresh(exam)
        await self.db.commit()
        return exam

    async def update_exam(
        self, exam_id: uuid.UUID, data: dict, owner_id: uuid.UUID
    ) -> Exam:
        exam = await self.get_exam(exam_id, owner_id)

        password = data.pop("password", None)
        if password:
            exam.password_hash = pwd_context.hash(password)

        for key, value in data.items():
            if value is not None and hasattr(exam, key):
                setattr(exam, key, value)
        await self.db.flush()
        await self.db.refresh(exam)
        await self.db.commit()
        return exam

    async def delete_exam(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID
    ) -> None:
        exam = await self.get_exam(exam_id, owner_id)
        await self.db.delete(exam)
        await self.db.flush()
        await self.db.commit()

    # ── Exam publishing ───────────────────────────────────────────────

    async def publish_exam(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Exam:
        exam = await self.get_exam(exam_id, owner_id)
        if exam.status != ExamStatus.DRAFT:
            raise HTTPException(400, "Only draft exams can be published")
        exam.status = ExamStatus.ACTIVE
        await self.db.flush()
        await self.db.refresh(exam)
        await self.db.commit()

        try:
            from app.modules.notifications.events import notify_exam_published

            await notify_exam_published(
                self.db, owner_id=owner_id, exam_title=exam.title,
            )
            await self.db.commit()
        except Exception:
            logger.warning("Failed to send exam published notification")

        return exam

    async def archive_exam(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Exam:
        exam = await self.get_exam(exam_id, owner_id)
        exam.status = ExamStatus.ARCHIVED
        await self.db.flush()
        await self.db.refresh(exam)
        await self.db.commit()
        return exam

    async def duplicate_exam(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Exam:
        await self._check_exam_quota(owner_id)

        original = await self.repo.get_by_id_owner(exam_id, owner_id)
        if not original:
            raise ExamNotFoundException()

        new_exam = Exam(
            title=f"{original.title} (Copy)",
            description=original.description,
            test_id=original.test_id,
            status=ExamStatus.DRAFT,
            visibility=original.visibility,
            start_time=original.start_time,
            end_time=original.end_time,
            duration_minutes=original.duration_minutes,
            passing_score=original.passing_score,
            max_attempts=original.max_attempts,
            owner_id=owner_id,
        )
        self.db.add(new_exam)
        await self.db.flush()
        await self.db.refresh(new_exam)
        await self.db.commit()
        return new_exam

    # ── Exam Participants ─────────────────────────────────────────────

    async def add_participant(
        self, exam_id: uuid.UUID, user_id: uuid.UUID, owner_id: uuid.UUID
    ) -> ExamParticipant:
        exam = await self.repo.get_by_id_owner(exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()
        await self._check_participant_quota(exam_id, exam.owner_id)
        return await self.participant_repo.add(exam_id, user_id)

    async def list_participants(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID
    ) -> list[ExamParticipant]:
        exam = await self.repo.get_by_id_owner(exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()
        return await self.participant_repo.list_by_exam(exam_id)

    async def remove_participant(
        self,
        exam_id: uuid.UUID,
        participant_id: uuid.UUID,
        owner_id: uuid.UUID,
    ) -> None:
        exam = await self.repo.get_by_id_owner(exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()
        await self.participant_repo.remove(exam_id, participant_id)

    # ── Attempts ──────────────────────────────────────────────────────

    async def start_attempt(
        self, exam_id: uuid.UUID, user_id: uuid.UUID
    ) -> ExamAttempt:
        exam_result = await self.db.execute(
            select(Exam)
            .options(
                selectinload(Exam.test)
                .selectinload(Test.test_questions)
                .selectinload(TestQuestion.test)
            )
            .where(Exam.id == exam_id, Exam.status == ExamStatus.ACTIVE)
        )
        exam = exam_result.scalar_one_or_none()
        if not exam:
            raise HTTPException(404, "Exam not found or not active")

        attempt_count = (
            await self.db.execute(
                select(func.count(ExamAttempt.id)).where(
                    ExamAttempt.exam_id == exam_id,
                    ExamAttempt.user_id == user_id,
                )
            )
        ).scalar_one()

        if attempt_count >= exam.max_attempts:
            raise HTTPException(
                400, f"Maximum attempts ({exam.max_attempts}) reached"
            )

        total_points = sum(
            tq.points for tq in exam.test.test_questions
        )

        attempt = ExamAttempt(
            exam_id=exam_id,
            user_id=user_id,
            total_points=total_points,
        )
        self.db.add(attempt)
        await self.db.flush()
        await self.db.refresh(attempt)
        await self.db.commit()
        return attempt

    @staticmethod
    def _grade_one(question, answer: dict) -> tuple[bool, int]:
        choices = question.choices if hasattr(question, "choices") else []
        pts = question.score if hasattr(question, "score") else 1

        qtype = question.question_type
        if hasattr(qtype, "value"):
            qtype = qtype.value

        if qtype in ("single_choice", "image"):
            sel = answer.get("selected_option_id")
            if not sel:
                return False, 0
            for c in choices:
                if c.id == sel and c.is_correct:
                    return True, pts
            return False, 0

        if qtype == "short_answer":
            ut = (answer.get("text_answer") or "").strip().lower()
            ct = (
                getattr(question, "correct_answer", None) or ""
            ).strip().lower()
            if not ut:
                return False, 0
            return (True, pts) if ut == ct else (False, 0)

        return False, 0

    async def submit_attempt(
        self,
        attempt_id: uuid.UUID,
        user_id: uuid.UUID,
        answers_data: list[dict],
    ) -> ExamAttempt:
        attempt_result = await self.db.execute(
            select(ExamAttempt)
            .options(
                selectinload(ExamAttempt.exam)
                .selectinload(Exam.test)
                .selectinload(Test.test_questions)
                .selectinload(TestQuestion.test)
                .selectinload(Test.settings),
                selectinload(ExamAttempt.answers),
            )
            .where(
                ExamAttempt.id == attempt_id,
                ExamAttempt.user_id == user_id,
            )
        )
        attempt = attempt_result.scalar_one_or_none()
        if not attempt:
            raise HTTPException(404, "Attempt not found")
        if attempt.is_completed:
            raise HTTPException(400, "Attempt already completed")

        questions_map: dict[uuid.UUID, object] = {}
        for tq in attempt.exam.test.test_questions:
            questions_map[tq.question_id] = tq

        total_score = 0
        for ans_data in answers_data:
            qid = ans_data.get("question_id")
            if not qid:
                continue
            tq = questions_map.get(qid)
            if not tq:
                continue

            question_result = await self.db.execute(
                select(QBQuestion)
                .options(selectinload(QBQuestion.choices))
                .where(QBQuestion.id == qid)
            )
            question = question_result.scalar_one_or_none()
            if not question:
                continue

            is_correct, points_earned = self._grade_one(
                question, ans_data
            )
            total_score += points_earned

            answer = QuestionAnswer(
                attempt_id=attempt.id,
                question_id=qid,
                selected_option_id=ans_data.get("selected_option_id"),
                text_answer=ans_data.get("text_answer"),
                is_correct=is_correct,
                points_earned=points_earned,
            )
            self.db.add(answer)

        attempt.score = total_score
        attempt.is_completed = True
        attempt.completed_at = self._now()

        await self.db.flush()
        await self.db.commit()

        try:
            from app.modules.notifications.events import notify_exam_completed

            await notify_exam_completed(
                self.db,
                student_id=user_id,
                exam_title=attempt.exam.title if attempt.exam else "Exam",
                score=total_score,
            )
            await self.db.commit()
        except Exception:
            logger.warning("Failed to send attempt completion notification")

        result = await self.db.execute(
            select(ExamAttempt)
            .options(selectinload(ExamAttempt.answers))
            .where(ExamAttempt.id == attempt.id)
        )
        return result.scalar_one()

    async def get_attempt(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID
    ) -> ExamAttempt:
        result = await self.db.execute(
            select(ExamAttempt)
            .options(selectinload(ExamAttempt.answers))
            .where(
                ExamAttempt.id == attempt_id,
                ExamAttempt.user_id == user_id,
            )
        )
        attempt = result.scalar_one_or_none()
        if not attempt:
            raise HTTPException(404, "Attempt not found")
        return attempt

    async def list_attempts(
        self, exam_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> dict:
        total = (
            await self.db.execute(
                select(func.count(ExamAttempt.id)).where(
                    ExamAttempt.exam_id == exam_id
                )
            )
        ).scalar_one()

        result = await self.db.execute(
            select(ExamAttempt)
            .where(ExamAttempt.exam_id == exam_id)
            .order_by(ExamAttempt.started_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        attempts = result.scalars().all()

        return {
            "items": attempts,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total > 0 else 1,
        }

    # NOTE: AI question generation was removed from here — it duplicated
    # app.modules.tests.service.TestService.generate_questions, which
    # already does the same thing (create Questions + link to the Test)
    # and is now plan-gated (PRO/PREMIUM). Use
    # POST /tests/{test_id}/ai-generate instead.
