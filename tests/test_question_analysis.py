"""Tests for TestService.analyze_questions (GET /tests/{id}/questions/analysis).

Builds a small, deterministic dataset where the expected p-value
(correct_rate) and point-biserial discrimination can be hand-verified,
then checks the service's output against it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.questions.models import DifficultyLevel, Question
from app.modules.tests.models import Test, TestPracticeAnswer, TestPracticeAttempt, TestQuestion
from app.modules.tests.service import TestService


@pytest.mark.asyncio
async def test_analyze_questions_flags_easy_and_discriminating_items(
    session: AsyncSession, test_user: User,
):
    now = datetime.now(UTC)

    test = Test(
        id=uuid.uuid4(), title="Analysis Test", test_type="quiz",
        status="active", owner_id=test_user.id,
    )
    q_easy = Question(
        id=uuid.uuid4(), title="Everyone gets this right", owner_id=test_user.id,
        difficulty=DifficultyLevel.EASY,
    )
    q_good = Question(
        id=uuid.uuid4(), title="Separates strong from weak", owner_id=test_user.id,
        difficulty=DifficultyLevel.MEDIUM,
    )
    session.add_all([test, q_easy, q_good])
    await session.flush()

    session.add_all([
        TestQuestion(id=uuid.uuid4(), test_id=test.id, question_id=q_easy.id, order=0),
        TestQuestion(id=uuid.uuid4(), test_id=test.id, question_id=q_good.id, order=1),
    ])
    await session.flush()

    # 5 "strong" attempts (100%) and 5 "weak" attempts (30%).
    for i in range(10):
        strong = i < 5
        attempt = TestPracticeAttempt(
            id=uuid.uuid4(), test_id=test.id, user_id=uuid.uuid4(),
            status="completed", percentage=100.0 if strong else 30.0,
            started_at=now - timedelta(days=1), completed_at=now - timedelta(days=1),
        )
        session.add(attempt)
        await session.flush()
        session.add_all([
            # Everyone gets q_easy right, regardless of group.
            TestPracticeAnswer(
                id=uuid.uuid4(), attempt_id=attempt.id, question_id=q_easy.id,
                is_correct=True,
            ),
            # q_good perfectly separates strong (correct) from weak (wrong).
            TestPracticeAnswer(
                id=uuid.uuid4(), attempt_id=attempt.id, question_id=q_good.id,
                is_correct=strong,
            ),
        ])
    await session.commit()

    service = TestService(session)
    result = await service.analyze_questions(test.id, test_user.id)

    assert result["questions_count"] == 2
    assert result["total_answers_considered"] == 20

    by_id = {item["question_id"]: item for item in result["items"]}
    easy = by_id[q_easy.id]
    good = by_id[q_good.id]

    assert easy["times_answered"] == 10
    assert easy["correct_rate"] == 100.0
    assert easy["flag"] == "too_easy"
    assert easy["discrimination"] is None  # no incorrect answers to compare against

    assert good["times_answered"] == 10
    assert good["correct_rate"] == 50.0
    assert good["discrimination"] == 1.0
    assert good["flag"] == "ok"


@pytest.mark.asyncio
async def test_analyze_questions_insufficient_data(session: AsyncSession, test_user: User):
    test = Test(
        id=uuid.uuid4(), title="Fresh Test", test_type="quiz",
        status="draft", owner_id=test_user.id,
    )
    question = Question(
        id=uuid.uuid4(), title="Never answered yet", owner_id=test_user.id,
        difficulty=DifficultyLevel.MEDIUM,
    )
    session.add_all([test, question])
    await session.flush()
    session.add(TestQuestion(id=uuid.uuid4(), test_id=test.id, question_id=question.id, order=0))
    await session.commit()

    service = TestService(session)
    result = await service.analyze_questions(test.id, test_user.id)

    assert result["questions_count"] == 1
    assert result["total_answers_considered"] == 0
    item = result["items"][0]
    assert item["times_answered"] == 0
    assert item["flag"] == "insufficient_data"
    assert item["discrimination"] is None
