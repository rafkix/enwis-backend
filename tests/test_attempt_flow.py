"""Integration tests for the student-facing "take an exam" pipeline —
the flow that powers exams.enwis.uz:

    start -> get questions (answer key stripped) -> save answers
    -> submit -> result / review

Each step re-reads with a *fresh* session (same pattern as
test_full_pipeline.py) so these tests catch both "not persisted" bugs
and the access-control / business-rule bugs fixed in this pass:

  - a student can never see `correct_answer` / `is_correct` while an
    attempt is still open (GET /exams/{attempt_id}/questions)
  - a student can only ever act on their own attempt
  - an exam's `max_attempts` and "one active attempt at a time" rules
    are enforced
  - a completed attempt can no longer be fetched/saved/submitted again
  - manual grading can't award more points than a question is worth
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.exams.attempt_exceptions import (
    AttemptAlreadyCompleted,
    DuplicateActiveAttempt,
    ExamTimeExpired,
    InvalidAnswerData,
    MaxAttemptsReached,
    NotAttemptOwner,
)
from app.modules.exams.attempt_service import AttemptService
from app.modules.exams.models import ExamAttempt
from app.modules.exams.service import ExamService
from app.modules.tests.question_service import QuestionService
from app.modules.tests.service import TestService


async def _commit(session: AsyncSession) -> None:
    await session.commit()


async def _build_published_exam(
    factory: async_sessionmaker, owner_id: uuid.UUID,
    max_attempts: int = 3, duration_minutes: int | None = 30,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Creates Test -> Question(single_choice, score=5) -> attach -> publish
    Test -> Exam -> publish Exam. Returns (exam_id, test_id, question_id).
    """
    async with factory() as s:
        question = await QuestionService(s).create_question(
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
            owner_id=owner_id,
        )
        question_id = question.id
        await _commit(s)

    async with factory() as s:
        test_service = TestService(s)
        test = await test_service.create_test(
            {"title": "Math Basics", "test_type": "quiz", "visibility": "private"},
            owner_id=owner_id,
        )
        test_id = test.id
        await test_service.add_question(test_id, question_id, owner_id, points=5)
        await test_service.publish_test(test_id, owner_id)
        await _commit(s)

    async with factory() as s:
        exam_service = ExamService(s)
        exam = await exam_service.create_exam(
            {
                "title": "Math Basics Exam",
                "test_id": test_id,
                "duration_minutes": duration_minutes,
                "passing_score": 50,
                "max_attempts": max_attempts,
            },
            owner_id=owner_id,
        )
        exam_id = exam.id
        await exam_service.publish_exam(exam_id, owner_id)
        await _commit(s)

    return exam_id, test_id, question_id


async def _correct_choice_id(factory: async_sessionmaker, question_id: uuid.UUID) -> uuid.UUID:
    from app.modules.questions.models import Question

    async with factory() as s:
        result = await s.execute(select(Question).where(Question.id == question_id))
        q = result.scalar_one()
        return next(c.id for c in q.choices if c.is_correct)


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_attempt_flow_start_to_result(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    exam_id, _test_id, question_id = await _build_published_exam(factory, test_user.id)

    # ── Start ────────────────────────────────────────────────────────
    async with factory() as s:
        started = await AttemptService(s).start_attempt(exam_id, test_user.id)
        attempt_id = started["id"]
        assert started["status"] == "in_progress"
        assert started["total_points"] == 5
        await _commit(s)

    # ── Get questions during the attempt — answer key must be hidden ──
    async with factory() as s:
        payload = await AttemptService(s).get_attempt_questions(attempt_id, test_user.id)
        assert payload["attempt_id"] == attempt_id
        assert len(payload["questions"]) == 1
        q = payload["questions"][0]
        assert q["id"] == question_id
        assert "correct_answer" not in q
        for opt in q["options"]:
            assert "is_correct" not in opt
        assert q["saved_answer"] is None

    # ── Save an answer (draft, not yet submitted) ──────────────────────
    correct_id = await _correct_choice_id(factory, question_id)
    async with factory() as s:
        result = await AttemptService(s).save_answers(
            attempt_id, test_user.id,
            [{"question_id": question_id, "selected_option_id": correct_id}],
        )
        assert result["success"] is True
        await _commit(s)

    # Saved answer should now come back on a fresh questions fetch.
    async with factory() as s:
        payload = await AttemptService(s).get_attempt_questions(attempt_id, test_user.id)
        saved = payload["questions"][0]["saved_answer"]
        assert saved is not None
        assert saved["selected_option_id"] == correct_id

    # ── Resume also reflects the saved answer / time remaining ────────
    async with factory() as s:
        resumed = await AttemptService(s).resume_attempt(attempt_id, test_user.id)
        assert resumed["questions_count"] == 1
        assert resumed["time_remaining_seconds"] is not None

    # ── Submit ──────────────────────────────────────────────────────
    async with factory() as s:
        submission = await AttemptService(s).submit_attempt(
            attempt_id, test_user.id,
            [{"question_id": question_id, "selected_option_id": correct_id}],
        )
        assert submission["status"] == "submitted"
        assert submission["score"] == 5
        assert submission["passed"] is True
        await _commit(s)

    # ── Result ──────────────────────────────────────────────────────
    async with factory() as s:
        result = await AttemptService(s).get_result(attempt_id, test_user.id)
        assert result["percentage"] == 100.0
        assert result["passed"] is True

    # ── Review — correct answers ARE shown once completed ─────────────
    async with factory() as s:
        review = await AttemptService(s).review_attempt(attempt_id, test_user.id)
        assert review is not None


# ── Answer-key leak regression (the bug we fixed) ──────────────────


@pytest.mark.asyncio
async def test_completed_attempt_cannot_fetch_questions_again(engine, test_user):
    """Once submitted, /questions must refuse (no more peeking at the
    exam, and definitely no more answer-key access)."""
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    exam_id, _test_id, question_id = await _build_published_exam(factory, test_user.id)

    async with factory() as s:
        started = await AttemptService(s).start_attempt(exam_id, test_user.id)
        attempt_id = started["id"]
        await _commit(s)

    correct_id = await _correct_choice_id(factory, question_id)
    async with factory() as s:
        await AttemptService(s).submit_attempt(
            attempt_id, test_user.id,
            [{"question_id": question_id, "selected_option_id": correct_id}],
        )
        await _commit(s)

    async with factory() as s:
        with pytest.raises(AttemptAlreadyCompleted):
            await AttemptService(s).get_attempt_questions(attempt_id, test_user.id)

    async with factory() as s:
        with pytest.raises(AttemptAlreadyCompleted):
            await AttemptService(s).save_answers(
                attempt_id, test_user.id,
                [{"question_id": question_id, "selected_option_id": correct_id}],
            )


# ── Ownership ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_other_user_cannot_access_someone_elses_attempt(engine, test_user, second_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    exam_id, _test_id, question_id = await _build_published_exam(factory, test_user.id)

    async with factory() as s:
        started = await AttemptService(s).start_attempt(exam_id, test_user.id)
        attempt_id = started["id"]
        await _commit(s)

    async with factory() as s:
        with pytest.raises(NotAttemptOwner):
            await AttemptService(s).get_attempt_questions(attempt_id, second_user.id)

    async with factory() as s:
        with pytest.raises(NotAttemptOwner):
            await AttemptService(s).save_answers(
                attempt_id, second_user.id,
                [{"question_id": question_id, "selected_option_id": None}],
            )

    async with factory() as s:
        with pytest.raises(NotAttemptOwner):
            await AttemptService(s).submit_attempt(attempt_id, second_user.id, [])

    async with factory() as s:
        with pytest.raises(NotAttemptOwner):
            await AttemptService(s).resume_attempt(attempt_id, second_user.id)


# ── Business rules: one active attempt, max attempts ───────────────


@pytest.mark.asyncio
async def test_cannot_start_two_active_attempts_at_once(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    exam_id, _test_id, _question_id = await _build_published_exam(factory, test_user.id)

    async with factory() as s:
        await AttemptService(s).start_attempt(exam_id, test_user.id)
        await _commit(s)

    async with factory() as s:
        with pytest.raises(DuplicateActiveAttempt):
            await AttemptService(s).start_attempt(exam_id, test_user.id)


@pytest.mark.asyncio
async def test_max_attempts_is_enforced(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    exam_id, _test_id, question_id = await _build_published_exam(
        factory, test_user.id, max_attempts=1,
    )
    correct_id = await _correct_choice_id(factory, question_id)

    async with factory() as s:
        started = await AttemptService(s).start_attempt(exam_id, test_user.id)
        attempt_id = started["id"]
        await _commit(s)

    async with factory() as s:
        await AttemptService(s).submit_attempt(
            attempt_id, test_user.id,
            [{"question_id": question_id, "selected_option_id": correct_id}],
        )
        await _commit(s)

    async with factory() as s:
        with pytest.raises(MaxAttemptsReached):
            await AttemptService(s).start_attempt(exam_id, test_user.id)


# ── Time expiry (regression test for the ExamTimeExpired guard added
#    to get_attempt_questions) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_expired_attempt_blocks_question_access(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    exam_id, _test_id, _question_id = await _build_published_exam(
        factory, test_user.id, duration_minutes=30,
    )

    async with factory() as s:
        started = await AttemptService(s).start_attempt(exam_id, test_user.id)
        attempt_id = started["id"]
        await _commit(s)

    # Simulate 40 minutes having passed on a 30-minute exam.
    async with factory() as s:
        await s.execute(
            update(ExamAttempt)
            .where(ExamAttempt.id == attempt_id)
            .values(started_at=datetime.now(UTC) - timedelta(minutes=40))
        )
        await s.commit()

    async with factory() as s:
        with pytest.raises(ExamTimeExpired):
            await AttemptService(s).get_attempt_questions(attempt_id, test_user.id)


# ── Manual grading cap (regression test for the points_earned cap) ─


@pytest.mark.asyncio
async def test_manual_grade_cannot_exceed_question_max_score(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    exam_id, _test_id, question_id = await _build_published_exam(factory, test_user.id)

    async with factory() as s:
        started = await AttemptService(s).start_attempt(exam_id, test_user.id)
        attempt_id = started["id"]
        await _commit(s)

    # Submit with no answer selected so it needs manual grading.
    async with factory() as s:
        await AttemptService(s).submit_attempt(
            attempt_id, test_user.id,
            [{"question_id": question_id, "selected_option_id": None}],
        )
        await _commit(s)

    # Question is worth 5 points — awarding 999 must be rejected.
    async with factory() as s:
        with pytest.raises(InvalidAnswerData):
            await AttemptService(s).manual_grade(
                attempt_id, question_id, test_user.id,
                points_earned=999,
            )

    # A negative score must also be rejected.
    async with factory() as s:
        with pytest.raises(InvalidAnswerData):
            await AttemptService(s).manual_grade(
                attempt_id, question_id, test_user.id,
                points_earned=-1,
            )

    # A valid, in-range score is accepted.
    async with factory() as s:
        graded = await AttemptService(s).manual_grade(
            attempt_id, question_id, test_user.id,
            points_earned=3,
        )
        assert graded["points_earned"] == 3
        await _commit(s)
