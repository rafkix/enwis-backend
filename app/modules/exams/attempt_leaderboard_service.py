import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.exams.models import Exam

if TYPE_CHECKING:
    from app.modules.exams.attempt_repository import AttemptRepository


class AttemptLeaderboardService:
    """Handles exam leaderboard functionality."""

    def __init__(self, db: AsyncSession, repo: "AttemptRepository"):
        self.db = db
        self.repo = repo

    @staticmethod
    def _compute_time_spent(started_at: datetime, completed_at: datetime | None) -> int:
        end = completed_at or datetime.now(UTC)
        return max(0, int((end - started_at).total_seconds()))

    async def get_leaderboard(self, exam_id: uuid.UUID, limit: int = 50) -> dict:
        r = await self.db.execute(select(Exam).where(Exam.id == exam_id))
        exam = r.scalar_one_or_none()
        exam_title = exam.title if exam else ""

        entries_raw = await self.repo.get_leaderboard(exam_id, limit)

        user_ids = [a.user_id for a in entries_raw]
        users_result = await self.db.execute(
            select(User).where(User.id.in_(user_ids)) if user_ids else select(User).where(False)
        )
        users_map = {u.id: u for u in users_result.scalars().all()}

        result_entries = []
        for idx, attempt in enumerate(entries_raw, start=1):
            user = users_map.get(attempt.user_id)
            total_points = attempt.total_points or 1
            score = attempt.score or 0
            percentage = round((score / total_points * 100), 2)
            time_spent = self._compute_time_spent(attempt.started_at, attempt.completed_at)

            result_entries.append({
                "rank": idx,
                "user_id": attempt.user_id,
                "username": user.username if user else None,
                "full_name": user.full_name if user else None,
                "avatar": user.avatar if user else None,
                "score": score,
                "total_points": total_points,
                "percentage": percentage,
                "time_spent_seconds": time_spent,
                "completed_at": attempt.completed_at,
            })

        return {
            "exam_id": exam_id,
            "exam_title": exam_title,
            "entries": result_entries,
            "total_entries": len(result_entries),
        }