"""Tests for the teacher-scoped dashboard (GET /dashboard/teacher).

Covers: permission gating (TEACHER/ADMIN only), and that the headline
numbers (students, tests, exams, questions, average score, average
difficulty, completion rate, pass/fail, recent activity, weekly/monthly
trend) are computed correctly from real Test/Exam/attempt rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User, UserStatus
from app.modules.dashboard.teacher_service import TeacherDashboardService
from app.modules.exams.models import Exam, ExamAttempt, ExamStatus, Result
from app.modules.questions.models import DifficultyLevel, Question
from app.modules.tests.models import Test, TestPracticeAttempt
from app.shared.permissions import require_teacher_or_admin


@pytest_asyncio.fixture
async def role_teacher(session: AsyncSession) -> Role:
    r = await session.execute(text("SELECT * FROM roles WHERE name = 'TEACHER'"))
    row = r.fetchone()
    if not row:
        role = Role(name="TEACHER", description="Teacher")
        session.add(role)
        await session.commit()
        await session.refresh(role)
        return role
    return Role(id=row[0], name=row[1], description=row[2])


@pytest_asyncio.fixture
async def teacher_user(session: AsyncSession, role_teacher: Role) -> User:
    user = User(
        id=uuid.uuid4(),
        username="teacheruser",
        phone="+998901112233",
        full_name="Teacher User",
        is_active=True,
        is_verified=True,
        status=UserStatus.ACTIVE,
    )
    user.roles.append(role_teacher)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def test_require_teacher_or_admin_rejects_plain_user(test_user: User):
    with pytest.raises(HTTPException) as exc:
        require_teacher_or_admin(test_user)
    assert exc.value.status_code == 403


def test_require_teacher_or_admin_allows_teacher(teacher_user: User):
    require_teacher_or_admin(teacher_user)  # must not raise


@pytest.mark.asyncio
async def test_teacher_dashboard_computes_real_numbers(
    session: AsyncSession,
    teacher_user: User,
    test_user: User,
    second_user: User,
):
    now = datetime.now(UTC)

    # Two tests owned by the teacher: one used for ungated practice, one
    # backing the exam below.
    practice_test = Test(
        id=uuid.uuid4(), title="Practice Test", test_type="practice",
        status="active", owner_id=teacher_user.id,
    )
    exam_test = Test(
        id=uuid.uuid4(), title="Exam Test", test_type="exam",
        status="active", owner_id=teacher_user.id,
    )
    session.add_all([practice_test, exam_test])
    await session.flush()

    exam = Exam(
        id=uuid.uuid4(), title="Midterm Exam", test_id=exam_test.id,
        owner_id=teacher_user.id, status=ExamStatus.ACTIVE,
    )
    session.add(exam)
    await session.flush()

    # Two questions with different calibration state.
    session.add_all([
        Question(
            id=uuid.uuid4(), title="Q1", owner_id=teacher_user.id,
            difficulty=DifficultyLevel.EASY, irt_b=None,
        ),
        Question(
            id=uuid.uuid4(), title="Q2", owner_id=teacher_user.id,
            difficulty=DifficultyLevel.HARD, irt_b=1.5,
        ),
    ])

    # student1 completes the practice test with 80%.
    session.add(
        TestPracticeAttempt(
            id=uuid.uuid4(), test_id=practice_test.id, user_id=test_user.id,
            status="completed", score=8, max_score=10, percentage=80.0,
            started_at=now - timedelta(days=1), completed_at=now - timedelta(days=1),
        )
    )

    # student2 completes the exam with 50% and fails.
    exam_attempt = ExamAttempt(
        id=uuid.uuid4(), exam_id=exam.id, user_id=second_user.id,
        score=5, total_points=10, is_completed=True,
        started_at=now - timedelta(days=2), completed_at=now - timedelta(days=2),
    )
    session.add(exam_attempt)
    await session.flush()
    session.add(
        Result(
            id=uuid.uuid4(), attempt_id=exam_attempt.id, total_score=5,
            max_score=10, percentage=50.0, passed=False,
            correct_count=5, wrong_count=5,
        )
    )
    await session.commit()

    service = TeacherDashboardService(session)
    dashboard = await service.get_teacher_dashboard(teacher_user)

    ov = dashboard.overview
    assert ov.total_tests == 2
    assert ov.total_exams == 1
    assert ov.total_questions == 2
    assert ov.total_students == 2
    assert ov.test_attempts == 1
    assert ov.exam_attempts == 1
    assert ov.total_attempts == 2
    assert ov.completion_rate == 100.0
    assert ov.average_score == 65.0  # (80 + 50) / 2
    # test-practice attempt (80% >= 60 threshold) counts as passed, exam
    # attempt is explicitly failed -> 1 pass, 1 fail.
    assert ov.pass_count == 1
    assert ov.fail_count == 1
    assert ov.success_rate == 50.0
    # average_difficulty: Q1 has no irt_b -> falls back to EASY (-1.0),
    # Q2 is calibrated at 1.5 -> mean is 0.25.
    assert ov.average_difficulty == 0.25
    assert ov.revenue == 0

    assert len(dashboard.recent_activity) == 2
    titles = {item.title for item in dashboard.recent_activity}
    assert titles == {"Practice Test", "Midterm Exam"}

    assert len(dashboard.weekly) == 8
    assert len(dashboard.monthly) == 6
    assert sum(p.attempts for p in dashboard.weekly) == 2
    assert sum(p.attempts for p in dashboard.monthly) == 2


@pytest.mark.asyncio
async def test_teacher_dashboard_empty_state(
    session: AsyncSession, teacher_user: User,
):
    service = TeacherDashboardService(session)
    dashboard = await service.get_teacher_dashboard(teacher_user)

    ov = dashboard.overview
    assert ov.total_tests == 0
    assert ov.total_students == 0
    assert ov.average_score == 0.0
    assert ov.completion_rate == 0.0
    assert ov.success_rate == 0.0
    assert dashboard.recent_activity == []
    assert len(dashboard.weekly) == 8
    assert all(p.attempts == 0 for p in dashboard.weekly)
