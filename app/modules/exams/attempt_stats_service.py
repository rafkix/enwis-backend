import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.exams.models import Exam

if TYPE_CHECKING:
    from app.modules.exams.attempt_repository import AttemptRepository


class AttemptStatsService:
    """Handles exam attempt statistics."""

    def __init__(self, db: AsyncSession, repo: "AttemptRepository"):
        self.db = db
        self.repo = repo

    async def get_exam_stats(self, exam_id: uuid.UUID) -> dict:
        attempts = await self.repo.get_all_completed_for_exam(exam_id)
        passing_score = await self._get_exam_passing_score(exam_id)

        total = len(attempts)
        if total == 0:
            return {
                "total_attempts": 0,
                "completed_attempts": 0,
                "average_score": 0.0,
                "average_percentage": 0.0,
                "highest_score": 0,
                "lowest_score": 0,
                "pass_count": 0,
                "fail_count": 0,
                "pass_rate": 0.0,
            }

        scores = [a.score or 0 for a in attempts]
        percentages = [
            round((a.score or 0) / (a.total_points or 1) * 100, 2)
            for a in attempts
        ]
        pass_count = sum(1 for p in percentages if p >= passing_score)

        return {
            "total_attempts": total,
            "completed_attempts": total,
            "average_score": round(sum(scores) / total, 2),
            "average_percentage": round(sum(percentages) / total, 2),
            "highest_score": max(scores),
            "lowest_score": min(scores),
            "pass_count": pass_count,
            "fail_count": total - pass_count,
            "pass_rate": round((pass_count / total * 100), 2) if total else 0.0,
        }

    async def _get_exam_passing_score(self, exam_id: uuid.UUID) -> int:
        result = await self.db.execute(select(Exam.passing_score).where(Exam.id == exam_id))
        return result.scalar_one_or_none() or 60