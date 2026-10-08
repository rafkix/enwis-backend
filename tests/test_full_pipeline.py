"""End-to-end test of the Test -> Question -> Exam -> Attempt -> Result
pipeline described in the product spec.

This intentionally uses a *fresh* session to re-read data after every
write (like a new HTTP request would), so it catches the "looks like it
worked but nothing was persisted" class of bug (missing commits) as well
as wiring/relationship bugs between modules.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Role, User, UserStatus
from app.modules.exams.models import Exam
from app.modules.exams.service import ExamService
from app.modules.exams.attempt_service import AttemptService
from app.modules.questions.models import Question
from app.modules.tests.question_service import QuestionService
from app.modules.tests.models import Test, TestQuestion
from app.modules.tests.service import TestService


async def _commit(session: AsyncSession) -> None:
    """Mimic app.core.database.get_db's commit-on-success behaviour."""
    await session.commit()


@pytest.mark.asyncio
async def test_full_test_question_exam_attempt_result_flow(engine, session, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # ── 1. Teacher creates a Test ──────────────────────────────────
    async with factory() as s1:
        test_service = TestService(s1)
        test = await test_service.create_test(
            {"title": "Math Basics", "test_type": "quiz", "visibility": "private"},
            owner_id=test_user.id,
        )
        test_id = test.id
        await _commit(s1)

    # Re-read with a brand new session to prove it was actually persisted.
    async with factory() as s2:
        result = await s2.execute(select(Test).where(Test.id == test_id))
        persisted_test = result.scalar_one_or_none()
        assert persisted_test is not None, "Test was not persisted!"
        assert persisted_test.status == "draft"

    # ── 2. Teacher creates a Question (manual) ─────────────────────
    async with factory() as s3:
        question_service = QuestionService(s3)
        question = await question_service.create_question(
            {
                "title": "2 + 2 = ?",
                "question_type": "single_choice",
                "difficulty": "easy",
                "score": 5,
                "choices": [
                    {"content": "3", "is_correct": False, "order": 0},
                    {"content": "4", "is_correct": True, "order": 1},
                    {"content": "5", "is_correct": False, "order": 2},
                ],
            },
            owner_id=test_user.id,
        )
        question_id = question.id
        await _commit(s3)

    # Re-read with a new session: this is exactly the bug that used to
    # silently swallow every created Question (QuestionRepository never
    # called session.commit()).
    async with factory() as s4:
        result = await s4.execute(select(Question).where(Question.id == question_id))
        persisted_question = result.scalar_one_or_none()
        assert persisted_question is not None, "Question was not persisted!"
        assert len(persisted_question.choices) == 3

    # ── 3. Question is attached to the Test ────────────────────────
    async with factory() as s5:
        test_service = TestService(s5)
        tq = await test_service.add_question(test_id, question_id, test_user.id)
        await _commit(s5)
        assert tq.test_id == test_id
        assert tq.question_id == question_id

    async with factory() as s6:
        result = await s6.execute(
            select(TestQuestion).where(TestQuestion.test_id == test_id)
        )
        links = list(result.scalars().all())
        assert len(links) == 1, "Question was not linked to the Test!"

    # ── 4. Teacher publishes the Test ───────────────────────────────
    async with factory() as s7:
        test_service = TestService(s7)
        published = await test_service.publish_test(test_id, test_user.id)
        assert published.status == "active"
        await _commit(s7)

    # ── 5. Teacher creates an Exam from the Test ────────────────────
    async with factory() as s8:
        exam_service = ExamService(s8)
        exam = await exam_service.create_exam(
            {
                "title": "Math Basics Exam",
                "test_id": test_id,
                "duration_minutes": 30,
                "passing_score": 50,
                "max_attempts": 3,
            },
            owner_id=test_user.id,
        )
        exam_id = exam.id
        await _commit(s8)

    async with factory() as s9:
        exam_service = ExamService(s9)
        published_exam = await exam_service.publish_exam(exam_id, test_user.id)
        assert published_exam.status.value == "active"
        await _commit(s9)

    async with factory() as s10:
        result = await s10.execute(select(Exam).where(Exam.id == exam_id))
        persisted_exam = result.scalar_one_or_none()
        assert persisted_exam is not None
        assert persisted_exam.test_id == test_id, "Exam is not linked to the Test!"

    # ── 6. Student starts an Attempt ────────────────────────────────
    async with factory() as s11:
        attempt_service = AttemptService(s11)
        started = await attempt_service.start_attempt(exam_id, test_user.id)
        attempt_id = started["id"]
        await _commit(s11)

    # ── 7. Student submits answers ───────────────────────────────────
    async with factory() as s12:
        attempt_service = AttemptService(s12)
        # fetch the correct choice id for the question we created
        q_result = await s12.execute(select(Question).where(Question.id == question_id))
        q = q_result.scalar_one()
        correct_choice = next(c for c in q.choices if c.is_correct)

        submission = await attempt_service.submit_attempt(
            attempt_id,
            test_user.id,
            [{"question_id": question_id, "selected_option_id": correct_choice.id}],
        )
        await _commit(s12)

    assert submission["status"] == "submitted"
    assert submission["correct_count"] == 1
    assert submission["score"] == 5
    assert submission["passed"] is True

    # ── 8. Result was computed and persisted ────────────────────────
    async with factory() as s13:
        attempt_service = AttemptService(s13)
        result = await attempt_service.get_result(attempt_id, test_user.id)
        assert result["percentage"] == 100.0
        assert result["passed"] is True
