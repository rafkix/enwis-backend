"""Teacher dashboard statistics.

Builds the teacher-facing dashboard entirely from data that already exists
in the schema:

- ``Test`` / ``Exam`` / ``Question`` rows owned by the teacher
- ``TestPracticeAttempt`` (ungated attempts on the teacher's Tests)
- ``ExamAttempt`` + ``Result`` (registered attempts on the teacher's Exams)

There is no student-roster table yet (that is the Student Management
module), so "student" here means *any distinct user who has attempted one
of this teacher's Tests or Exams*. This is an explicit, documented
approximation — once a roster/enrollment table exists, total/active
students should be redefined against it.

All period-bucketing (weekly/monthly) is done in Python rather than with
SQL date-truncation functions, so this works identically against
PostgreSQL (production) and SQLite (tests).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.dashboard.teacher_schemas import (
    PeriodPoint,
    RecentActivityItem,
    TeacherDashboardResponse,
    TeacherOverview,
)
from app.modules.exams.models import Exam, ExamAttempt, Result
from app.modules.questions.models import DifficultyLevel, Question
from app.modules.tests.models import Test, TestPracticeAttempt

RECENT_ACTIVITY_LIMIT = 10
ACTIVE_WINDOW_DAYS = 30
WEEKLY_PERIODS = 8
MONTHLY_PERIODS = 6

_DIFFICULTY_FALLBACK = {
    DifficultyLevel.EASY: -1.0,
    DifficultyLevel.MEDIUM: 0.0,
    DifficultyLevel.HARD: 1.0,
}


def _as_aware_utc(dt: datetime | None) -> datetime | None:
    """Normalize a timestamp coming back from the DB driver to tz-aware UTC.

    PostgreSQL (production) returns tz-aware datetimes for
    ``DateTime(timezone=True)`` columns, but SQLite (used in tests) always
    hands back naive ones — comparing the two raises ``TypeError``. Treat
    any naive value as already being UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@dataclass
class _ActivityRecord:
    source: str  # "test" | "exam"
    user_id: uuid.UUID
    title: str
    percentage: float
    completed: bool
    passed: bool | None
    timestamp: datetime | None


class TeacherDashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_teacher_dashboard(self, teacher: User) -> TeacherDashboardResponse:
        test_ids = await self._owned_test_ids(teacher.id)
        exam_ids = await self._owned_exam_ids(teacher.id)

        test_activity = await self._fetch_test_activity(test_ids)
        exam_activity = await self._fetch_exam_activity(exam_ids)
        all_records = test_activity + exam_activity

        total_questions = await self._count_questions(teacher.id)
        average_difficulty = await self._average_difficulty(teacher.id)

        overview = self._build_overview(
            total_tests=len(test_ids),
            total_exams=len(exam_ids),
            total_questions=total_questions,
            test_activity=test_activity,
            exam_activity=exam_activity,
        )
        overview.average_difficulty = average_difficulty

        recent_activity = await self._build_recent_activity(all_records)
        weekly = self._bucket_by_period(all_records, granularity="week", periods=WEEKLY_PERIODS)
        monthly = self._bucket_by_period(all_records, granularity="month", periods=MONTHLY_PERIODS)

        return TeacherDashboardResponse(
            overview=overview,
            recent_activity=recent_activity,
            weekly=weekly,
            monthly=monthly,
        )

    # ── Ownership scoping ────────────────────────────────────────────

    async def _owned_test_ids(self, teacher_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self.db.execute(
            select(Test.id).where(Test.owner_id == teacher_id, Test.deleted_at.is_(None))
        )
        return [row[0] for row in rows.all()]

    async def _owned_exam_ids(self, teacher_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self.db.execute(
            select(Exam.id).where(Exam.owner_id == teacher_id, Exam.deleted_at.is_(None))
        )
        return [row[0] for row in rows.all()]

    async def _count_questions(self, teacher_id: uuid.UUID) -> int:
        return (
            await self.db.execute(
                select(func.count(Question.id)).where(
                    Question.owner_id == teacher_id, Question.deleted_at.is_(None)
                )
            )
        ).scalar() or 0

    async def _average_difficulty(self, teacher_id: uuid.UUID) -> float:
        rows = (
            await self.db.execute(
                select(Question.difficulty, Question.irt_b).where(
                    Question.owner_id == teacher_id, Question.deleted_at.is_(None)
                )
            )
        ).all()
        if not rows:
            return 0.0
        values = [
            irt_b if irt_b is not None else _DIFFICULTY_FALLBACK.get(difficulty, 0.0)
            for difficulty, irt_b in rows
        ]
        return round(sum(values) / len(values), 4)

    # ── Activity fetch ───────────────────────────────────────────────

    async def _fetch_test_activity(self, test_ids: list[uuid.UUID]) -> list[_ActivityRecord]:
        if not test_ids:
            return []
        rows = (
            await self.db.execute(
                select(
                    TestPracticeAttempt.user_id,
                    TestPracticeAttempt.percentage,
                    TestPracticeAttempt.status,
                    TestPracticeAttempt.started_at,
                    TestPracticeAttempt.completed_at,
                    Test.title,
                )
                .join(Test, Test.id == TestPracticeAttempt.test_id)
                .where(TestPracticeAttempt.test_id.in_(test_ids))
            )
        ).all()

        records: list[_ActivityRecord] = []
        for user_id, percentage, status, started_at, completed_at, title in rows:
            completed = status == "completed"
            records.append(
                _ActivityRecord(
                    source="test",
                    user_id=user_id,
                    title=title,
                    percentage=percentage or 0.0,
                    completed=completed,
                    # No pass/fail threshold is configured for ungated test
                    # practice — approximate with a 60% bar, same as the
                    # platform-wide default passing_score on Exam.
                    passed=(percentage or 0.0) >= 60.0 if completed else None,
                    timestamp=_as_aware_utc(completed_at or started_at),
                )
            )
        return records

    async def _fetch_exam_activity(self, exam_ids: list[uuid.UUID]) -> list[_ActivityRecord]:
        if not exam_ids:
            return []
        rows = (
            await self.db.execute(
                select(
                    ExamAttempt.user_id,
                    ExamAttempt.is_completed,
                    ExamAttempt.started_at,
                    ExamAttempt.completed_at,
                    Exam.title,
                    Result.percentage,
                    Result.passed,
                )
                .join(Exam, Exam.id == ExamAttempt.exam_id)
                .outerjoin(Result, Result.attempt_id == ExamAttempt.id)
                .where(ExamAttempt.exam_id.in_(exam_ids))
            )
        ).all()

        records: list[_ActivityRecord] = []
        for user_id, is_completed, started_at, completed_at, title, result_pct, passed in rows:
            records.append(
                _ActivityRecord(
                    source="exam",
                    user_id=user_id,
                    title=title,
                    percentage=result_pct if result_pct is not None else 0.0,
                    completed=bool(is_completed),
                    passed=passed,
                    timestamp=_as_aware_utc(completed_at or started_at),
                )
            )
        return records

    # ── Aggregation ──────────────────────────────────────────────────

    def _build_overview(
        self,
        *,
        total_tests: int,
        total_exams: int,
        total_questions: int,
        test_activity: list[_ActivityRecord],
        exam_activity: list[_ActivityRecord],
    ) -> TeacherOverview:
        all_records = test_activity + exam_activity
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=ACTIVE_WINDOW_DAYS)

        student_ids = {r.user_id for r in all_records}
        active_students = {
            r.user_id for r in all_records if r.timestamp and r.timestamp >= cutoff
        }

        first_seen: dict[uuid.UUID, datetime] = {}
        for r in all_records:
            if r.timestamp is None:
                continue
            if r.user_id not in first_seen or r.timestamp < first_seen[r.user_id]:
                first_seen[r.user_id] = r.timestamp
        student_growth_30d = sum(1 for ts in first_seen.values() if ts >= cutoff)

        completed_records = [r for r in all_records if r.completed]
        total_attempts = len(all_records)
        completion_rate = (
            round(len(completed_records) / total_attempts * 100, 2) if total_attempts else 0.0
        )
        average_score = (
            round(sum(r.percentage for r in completed_records) / len(completed_records), 2)
            if completed_records
            else 0.0
        )

        graded = [r for r in completed_records if r.passed is not None]
        pass_count = sum(1 for r in graded if r.passed)
        fail_count = len(graded) - pass_count
        success_rate = round(pass_count / len(graded) * 100, 2) if graded else 0.0

        return TeacherOverview(
            total_students=len(student_ids),
            active_students=len(active_students),
            student_growth_30d=student_growth_30d,
            total_tests=total_tests,
            total_exams=total_exams,
            total_questions=total_questions,
            test_attempts=len(test_activity),
            exam_attempts=len(exam_activity),
            total_attempts=total_attempts,
            average_score=average_score,
            completion_rate=completion_rate,
            success_rate=success_rate,
            pass_count=pass_count,
            fail_count=fail_count,
            revenue=0,
        )

    async def _build_recent_activity(
        self, all_records: list[_ActivityRecord]
    ) -> list[RecentActivityItem]:
        combined = sorted(
            (r for r in all_records if r.timestamp is not None),
            key=lambda r: r.timestamp,
            reverse=True,
        )[:RECENT_ACTIVITY_LIMIT]
        if not combined:
            return []

        user_ids = {r.user_id for r in combined}
        rows = (
            await self.db.execute(
                select(User.id, User.full_name, User.username).where(User.id.in_(user_ids))
            )
        ).all()
        names = {uid: (full_name or username) for uid, full_name, username in rows}

        return [
            RecentActivityItem(
                source=r.source,
                title=r.title,
                student_id=r.user_id,
                student_name=names.get(r.user_id, "—"),
                score_percentage=round(r.percentage, 2),
                completed_at=r.timestamp,
            )
            for r in combined
        ]

    def _bucket_by_period(
        self, all_records: list[_ActivityRecord], *, granularity: str, periods: int
    ) -> list[PeriodPoint]:
        def week_key(dt: datetime) -> str:
            iso = dt.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"

        def month_key(dt: datetime) -> str:
            return f"{dt.year}-{dt.month:02d}"

        key_fn = week_key if granularity == "week" else month_key
        step = timedelta(days=7) if granularity == "week" else timedelta(days=30)

        now = datetime.now(UTC)
        period_keys: list[str] = []
        cursor = now
        seen: set[str] = set()
        while len(period_keys) < periods:
            k = key_fn(cursor)
            if k not in seen:
                period_keys.append(k)
                seen.add(k)
            cursor -= step
        period_keys.reverse()

        # First-ever activity timestamp per student, computed across *all*
        # records (not just the window) so growth attributes correctly to
        # the period the student actually first showed up in.
        first_seen: dict[uuid.UUID, datetime] = {}
        for r in all_records:
            if r.timestamp is None:
                continue
            if r.user_id not in first_seen or r.timestamp < first_seen[r.user_id]:
                first_seen[r.user_id] = r.timestamp

        buckets: dict[str, dict] = {
            k: {"attempts": 0, "scores": [], "new_students": 0} for k in period_keys
        }
        counted_growth: set[uuid.UUID] = set()

        timestamped = sorted(
            (r for r in all_records if r.timestamp is not None), key=lambda r: r.timestamp
        )
        for r in timestamped:
            k = key_fn(r.timestamp)
            if k not in buckets:
                continue
            buckets[k]["attempts"] += 1
            if r.completed:
                buckets[k]["scores"].append(r.percentage)
            if (
                r.user_id not in counted_growth
                and first_seen.get(r.user_id) == r.timestamp
            ):
                counted_growth.add(r.user_id)
                buckets[k]["new_students"] += 1

        return [
            PeriodPoint(
                period=k,
                attempts=v["attempts"],
                new_students=v["new_students"],
                average_score=round(sum(v["scores"]) / len(v["scores"]), 2)
                if v["scores"]
                else 0.0,
            )
            for k, v in buckets.items()
        ]
