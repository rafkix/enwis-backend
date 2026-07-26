from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.dashboard.schemas import (
    AttemptStats,
    CertificateStats,
    DashboardStatsResponse,
    ExamStats,
    PlatformStats,
    PublicStatsResponse,
    QuestionStats,
    TestStats,
    UserStats,
)
from app.modules.exams.models import Certificate, Exam, ExamAttempt, Result
from app.modules.notifications.models import Notification
from app.modules.questions.models import Question
from app.modules.tests.models import Test

logger = logging.getLogger(__name__)


class DashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_user_stats(self, user: User) -> DashboardStatsResponse:
        user_stats = UserStats(
            xp=getattr(user, "xp", 0),
            level=getattr(user, "level", 1),
            streak=getattr(user, "streak", 0),
            subscription_tier=user.subscription_tier or "free",
        )

        test_stats = await self._get_test_stats(user.id)
        question_stats = await self._get_question_stats(user.id)
        exam_stats = await self._get_exam_stats(user.id)
        attempt_stats = await self._get_attempt_stats(user.id)
        cert_stats = await self._get_certificate_stats(user.id)
        unread = await self._get_unread_notifications(user.id)

        return DashboardStatsResponse(
            user=user_stats,
            tests=test_stats,
            questions=question_stats,
            exams=exam_stats,
            attempts=attempt_stats,
            certificates=cert_stats,
            unread_notifications=unread,
        )

    async def _get_test_stats(self, user_id: uuid.UUID) -> TestStats:
        base = select(func.count(Test.id)).where(Test.owner_id == user_id)
        total = (await self.db.execute(base)).scalar() or 0
        draft = (
            await self.db.execute(
                base.where(Test.status == "draft")
            )
        ).scalar() or 0
        active = (
            await self.db.execute(
                base.where(Test.status == "active")
            )
        ).scalar() or 0
        archived = (
            await self.db.execute(
                base.where(Test.status == "archived")
            )
        ).scalar() or 0
        return TestStats(total=total, draft=draft, active=active, archived=archived)

    async def _get_question_stats(self, user_id: uuid.UUID) -> QuestionStats:
        base = select(func.count(Question.id)).where(Question.owner_id == user_id)
        total = (await self.db.execute(base)).scalar() or 0

        type_rows = (
            await self.db.execute(
                select(Question.question_type, func.count(Question.id))
                .where(Question.owner_id == user_id)
                .group_by(Question.question_type)
            )
        ).all()
        by_type = {
            row[0].value if hasattr(row[0], "value") else str(row[0]): row[1]
            for row in type_rows
        }

        diff_rows = (
            await self.db.execute(
                select(Question.difficulty, func.count(Question.id))
                .where(Question.owner_id == user_id)
                .group_by(Question.difficulty)
            )
        ).all()
        by_difficulty = {
            row[0].value if hasattr(row[0], "value") else str(row[0]): row[1]
            for row in diff_rows
        }

        return QuestionStats(total=total, by_type=by_type, by_difficulty=by_difficulty)

    async def _get_exam_stats(self, user_id: uuid.UUID) -> ExamStats:
        base = select(func.count(Exam.id)).where(Exam.owner_id == user_id)
        total = (await self.db.execute(base)).scalar() or 0
        active = (
            await self.db.execute(
                base.where(Exam.status == "active")
            )
        ).scalar() or 0
        return ExamStats(exams_created=total, exams_active=active)

    async def _get_attempt_stats(self, user_id: uuid.UUID) -> AttemptStats:
        result = await self.db.execute(
            select(ExamAttempt)
            .where(ExamAttempt.user_id == user_id, ExamAttempt.is_completed.is_(True))
        )
        attempts = list(result.scalars().all())

        if not attempts:
            return AttemptStats()

        total = len(attempts)
        scores = [a.score or 0 for a in attempts]
        totals = [a.total_points or 1 for a in attempts]
        percentages = [
            round(s / t * 100, 2) for s, t in zip(scores, totals, strict=True)
        ]

        # Get pass/fail from results table
        attempt_ids = [a.id for a in attempts]
        result_rows = (
            await self.db.execute(
                select(Result.passed).where(Result.attempt_id.in_(attempt_ids))
            )
        ).scalars().all()
        pass_count = sum(1 for p in result_rows if p)
        fail_count = total - pass_count

        return AttemptStats(
            total_attempts=total,
            completed_attempts=total,
            average_score=round(sum(scores) / total, 2),
            average_percentage=round(sum(percentages) / total, 2),
            best_percentage=max(percentages),
            worst_percentage=min(percentages),
            pass_count=pass_count,
            fail_count=fail_count,
            pass_rate=round(pass_count / total * 100, 2) if total else 0.0,
        )

    async def _get_certificate_stats(self, user_id: uuid.UUID) -> CertificateStats:
        total = (
            await self.db.execute(
                select(func.count(Certificate.id)).where(Certificate.user_id == user_id)
            )
        ).scalar() or 0
        return CertificateStats(total=total)

    async def _get_unread_notifications(self, user_id: uuid.UUID) -> int:
        return (
            await self.db.execute(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user_id,
                    Notification.is_read.is_(False),
                )
            )
        ).scalar() or 0


class PublicStatsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_platform_stats(self) -> PublicStatsResponse:
        total_users = (await self.db.execute(select(func.count(User.id)))).scalar() or 0
        active_users = (
            await self.db.execute(
                select(func.count(User.id)).where(User.is_active.is_(True))
            )
        ).scalar() or 0
        total_tests = (await self.db.execute(select(func.count(Test.id)))).scalar() or 0
        total_questions = (
            await self.db.execute(select(func.count(Question.id)))
        ).scalar() or 0
        total_exams = (await self.db.execute(select(func.count(Exam.id)))).scalar() or 0
        total_attempts = (
            await self.db.execute(select(func.count(ExamAttempt.id)))
        ).scalar() or 0
        total_certificates = (
            await self.db.execute(select(func.count(Certificate.id)))
        ).scalar() or 0

        return PublicStatsResponse(
            platform=PlatformStats(
                total_users=total_users,
                active_users=active_users,
                total_tests=total_tests,
                total_questions=total_questions,
                total_exams=total_exams,
                total_attempts=total_attempts,
                total_certificates=total_certificates,
            )
        )
