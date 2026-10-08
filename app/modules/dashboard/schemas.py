from __future__ import annotations

from pydantic import BaseModel, Field


class UserStats(BaseModel):
    xp: int = 0
    level: int = 1
    streak: int = 0
    subscription_tier: str = "free"


class TestStats(BaseModel):
    total: int = 0
    draft: int = 0
    active: int = 0
    archived: int = 0


class QuestionStats(BaseModel):
    total: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_difficulty: dict[str, int] = Field(default_factory=dict)


class ExamStats(BaseModel):
    exams_created: int = 0
    exams_active: int = 0


class AttemptStats(BaseModel):
    total_attempts: int = 0
    completed_attempts: int = 0
    average_score: float = 0.0
    average_percentage: float = 0.0
    best_percentage: float = 0.0
    worst_percentage: float = 0.0
    pass_count: int = 0
    fail_count: int = 0
    pass_rate: float = 0.0


class CertificateStats(BaseModel):
    total: int = 0


class DashboardStatsResponse(BaseModel):
    user: UserStats
    tests: TestStats
    questions: QuestionStats
    exams: ExamStats
    attempts: AttemptStats
    certificates: CertificateStats
    unread_notifications: int = 0


class PlatformStats(BaseModel):
    total_users: int = 0
    active_users: int = 0
    total_tests: int = 0
    total_questions: int = 0
    total_exams: int = 0
    total_attempts: int = 0
    total_certificates: int = 0


class PublicStatsResponse(BaseModel):
    platform: PlatformStats
