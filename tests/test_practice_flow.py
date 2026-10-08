"""Tests for 'Test is also Playable' — the practice-attempt flow that
powers test.enwis.uz (start/save/submit/result/attempts, no Exam or
registration involved at all).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.tests.practice_service import (
    NotPracticeAttemptOwner,
    PracticeAttemptAlreadyCompleted,
    TestNotPlayable,
    TestPracticeService,
)
from app.modules.tests.service import TestService


async def _build_published_test(factory, owner_id):
    async with factory() as s:
        test = await TestService(s).create_test(
            {"title": "Playable Quiz", "test_type": "quiz", "visibility": "public"},
            owner_id=owner_id,
        )
        test_id = test.id
        await s.commit()

    async with factory() as s:
        question = await TestService(s).create_question_in_test(
            test_id,
            {
                "title": "1 + 1 = ?",
                "question_type": "single_choice",
                "score": 2,
                "choices": [
                    {"content": "1", "is_correct": False, "order": 0},
                    {"content": "2", "is_correct": True, "order": 1},
                ],
            },
            owner_id,
        )
        question_id = question.id
        correct_id = next(c.id for c in question.choices if c.is_correct)

    async with factory() as s:
        await TestService(s).publish_test(test_id, owner_id)
        await s.commit()

    return test_id, question_id, correct_id


@pytest.mark.asyncio
async def test_cannot_play_a_draft_test(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        test = await TestService(s).create_test(
            {"title": "Draft Quiz", "test_type": "quiz", "visibility": "public"},
            owner_id=test_user.id,
        )
        test_id = test.id
        await s.commit()

    async with factory() as s:
        with pytest.raises(TestNotPlayable):
            await TestPracticeService(s).start(test_id, test_user.id)


@pytest.mark.asyncio
async def test_full_practice_flow_start_to_result(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    test_id, question_id, correct_id = await _build_published_test(factory, test_user.id)

    async with factory() as s:
        started = await TestPracticeService(s).start(test_id, test_user.id)
        attempt_id = started["id"]
        assert started["status"] == "in_progress"
        assert started["max_score"] == 2

    async with factory() as s:
        saved = await TestPracticeService(s).save(
            attempt_id, test_user.id,
            [{"question_id": question_id, "selected_option_id": correct_id}],
        )
        assert saved["success"] is True

    async with factory() as s:
        submitted = await TestPracticeService(s).submit(attempt_id, test_user.id, [])
        assert submitted["status"] == "completed"
        assert submitted["score"] == 2
        assert submitted["percentage"] == 100.0

    async with factory() as s:
        result = await TestPracticeService(s).get_result(attempt_id, test_user.id)
        assert result["score"] == 2
        assert result["answers"][0]["is_correct"] is True

    async with factory() as s:
        attempts = await TestPracticeService(s).list_attempts(test_id, test_user.id)
        assert len(attempts) == 1
        assert attempts[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_starting_twice_resumes_the_same_attempt(engine, test_user):
    """start() is idempotent: calling it again while an attempt is
    in_progress (e.g. a page reload) returns the SAME attempt with its
    questions, rather than 400ing."""
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    test_id, question_id, _cid = await _build_published_test(factory, test_user.id)

    async with factory() as s:
        first = await TestPracticeService(s).start(test_id, test_user.id)

    async with factory() as s:
        second = await TestPracticeService(s).start(test_id, test_user.id)

    assert second["id"] == first["id"]
    assert second["status"] == "in_progress"
    assert len(second["questions"]) == 1
    assert second["questions"][0]["id"] == question_id
    assert "is_correct" not in second["questions"][0]["choices"][0]


@pytest.mark.asyncio
async def test_other_user_cannot_touch_someone_elses_practice_attempt(
    engine, test_user, second_user,
):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    test_id, question_id, correct_id = await _build_published_test(factory, test_user.id)

    async with factory() as s:
        started = await TestPracticeService(s).start(test_id, test_user.id)
        attempt_id = started["id"]

    async with factory() as s:
        with pytest.raises(NotPracticeAttemptOwner):
            await TestPracticeService(s).save(
                attempt_id, second_user.id,
                [{"question_id": question_id, "selected_option_id": correct_id}],
            )

    async with factory() as s:
        with pytest.raises(NotPracticeAttemptOwner):
            await TestPracticeService(s).submit(attempt_id, second_user.id, [])


@pytest.mark.asyncio
async def test_completed_practice_attempt_cannot_be_resubmitted(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    test_id, question_id, correct_id = await _build_published_test(factory, test_user.id)

    async with factory() as s:
        started = await TestPracticeService(s).start(test_id, test_user.id)
        attempt_id = started["id"]

    async with factory() as s:
        await TestPracticeService(s).submit(
            attempt_id, test_user.id,
            [{"question_id": question_id, "selected_option_id": correct_id}],
        )

    async with factory() as s:
        with pytest.raises(PracticeAttemptAlreadyCompleted):
            await TestPracticeService(s).submit(attempt_id, test_user.id, [])

    async with factory() as s:
        with pytest.raises(PracticeAttemptAlreadyCompleted):
            await TestPracticeService(s).save(
                attempt_id, test_user.id,
                [{"question_id": question_id, "selected_option_id": correct_id}],
            )
