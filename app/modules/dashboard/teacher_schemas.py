from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TeacherOverview(BaseModel):
    """Headline numbers for a teacher's own dashboard.

    ``total_students`` / ``active_students`` / ``student_growth_30d`` are
    computed from *activity* (distinct users who attempted this teacher's
    Tests or Exams) — there is no dedicated student-roster table yet. Once
    the Student Management module ships, these should be redefined against
    the roster (enrolled students) rather than pure attempt history.
    """

    total_students: int = 0
    active_students: int = 0
    student_growth_30d: int = 0

    total_tests: int = 0
    total_exams: int = 0
    total_questions: int = 0

    test_attempts: int = 0
    exam_attempts: int = 0
    total_attempts: int = 0

    average_score: float = 0.0
    average_difficulty: float = 0.0
    completion_rate: float = 0.0

    success_rate: float = 0.0
    pass_count: int = 0
    fail_count: int = 0

    # No paid-test/paid-exam monetization exists in the schema yet, so this
    # is always 0 for now rather than a fabricated number. Wire this up once
    # a pricing field lands on Test/Exam.
    revenue: int = 0


class RecentActivityItem(BaseModel):
    source: str  # "test" | "exam"
    title: str
    student_id: uuid.UUID
    student_name: str
    score_percentage: float
    completed_at: datetime | None = None


class PeriodPoint(BaseModel):
    period: str
    attempts: int
    new_students: int
    average_score: float


class TeacherDashboardResponse(BaseModel):
    overview: TeacherOverview
    recent_activity: list[RecentActivityItem] = Field(default_factory=list)
    weekly: list[PeriodPoint] = Field(default_factory=list)
    monthly: list[PeriodPoint] = Field(default_factory=list)
