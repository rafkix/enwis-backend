"""Tests for the ENWIS architecture refactor: Question is no longer an
independent module/API — it is managed entirely inside Test.

Covers:
  - there is no public /questions/* router anymore
  - creating/listing/updating/deleting a question through /tests/{id}/questions
  - deleting a question that's only used by this Test also removes the
    underlying Question entity (no orphaned "independent" questions)
  - JSON import/export round-trips through the Test
  - preview / statistics endpoints
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.questions.models import Question
from app.modules.tests.service import (
    TestQuestionNotFoundException,
    TestService,
)


def test_no_public_questions_router():
    """There must be no /questions/* route left in the app at all."""
    from app.main import app

    question_paths = [
        r.path for r in app.routes
        if hasattr(r, "path") and r.path.startswith("/api/v1/questions")
    ]
    assert question_paths == []


@pytest.mark.asyncio
async def test_create_list_update_delete_question_via_test(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as s:
        test = await TestService(s).create_test(
            {"title": "Geography", "test_type": "quiz", "visibility": "private"},
            owner_id=test_user.id,
        )
        test_id = test.id
        await s.commit()

    # ── Create a question directly through the Test ────────────────────
    async with factory() as s:
        question = await TestService(s).create_question_in_test(
            test_id,
            {
                "title": "Capital of France?",
                "question_type": "single_choice",
                "difficulty": "easy",
                "score": 4,
                "choices": [
                    {"content": "Paris", "is_correct": True, "order": 0},
                    {"content": "Lyon", "is_correct": False, "order": 1},
                ],
            },
            test_user.id,
        )
        question_id = question.id
        assert question.title == "Capital of France?"
        assert len(question.choices) == 2

    # ── List reflects it ────────────────────────────────────────────
    async with factory() as s:
        questions = await TestService(s).list_questions_full(test_id, test_user.id)
        assert len(questions) == 1
        assert questions[0].id == question_id

    # ── Update through the Test ─────────────────────────────────────
    async with factory() as s:
        updated = await TestService(s).update_question_in_test(
            test_id, question_id, {"title": "What is the capital of France?"},
            test_user.id,
        )
        assert updated.title == "What is the capital of France?"

    # ── Delete: link removed AND underlying Question gone (only Test) ──
    async with factory() as s:
        await TestService(s).delete_question_from_test(test_id, question_id, test_user.id)

    async with factory() as s:
        result = await s.execute(select(Question).where(Question.id == question_id))
        assert result.scalar_one_or_none() is None

        with pytest.raises(TestQuestionNotFoundException):
            await TestService(s).update_question_in_test(
                test_id, question_id, {"title": "x"}, test_user.id,
            )


@pytest.mark.asyncio
async def test_json_import_export_round_trip(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as s:
        test = await TestService(s).create_test(
            {"title": "Import Test", "test_type": "quiz", "visibility": "private"},
            owner_id=test_user.id,
        )
        test_id = test.id
        await s.commit()

    payload = [
        {
            "title": "2 + 2 = ?",
            "question_type": "single_choice",
            "score": 5,
            "choices": [
                {"content": "3", "is_correct": False, "order": 0},
                {"content": "4", "is_correct": True, "order": 1},
            ],
        },
        {
            "title": "Capital of Uzbekistan?",
            "question_type": "single_choice",
            "score": 5,
            "choices": [
                {"content": "Tashkent", "is_correct": True, "order": 0},
                {"content": "Samarqand", "is_correct": False, "order": 1},
            ],
        },
    ]

    async with factory() as s:
        created = await TestService(s).import_questions_json(test_id, payload, test_user.id)
        assert len(created) == 2

    async with factory() as s:
        exported = await TestService(s).export_questions_json(test_id, test_user.id)
        assert len(exported) == 2
        titles = {q["title"] for q in exported}
        assert titles == {"2 + 2 = ?", "Capital of Uzbekistan?"}


@pytest.mark.asyncio
async def test_preview_and_statistics(engine, test_user):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as s:
        test = await TestService(s).create_test(
            {"title": "Stats Test", "test_type": "quiz", "visibility": "private"},
            owner_id=test_user.id,
        )
        test_id = test.id
        await s.commit()

    async with factory() as s:
        await TestService(s).create_question_in_test(
            test_id,
            {
                "title": "Q1", "question_type": "single_choice", "score": 3,
                "choices": [
                    {"content": "A", "is_correct": True, "order": 0},
                    {"content": "B", "is_correct": False, "order": 1},
                ],
            },
            test_user.id,
        )

    async with factory() as s:
        preview = await TestService(s).preview_test(test_id, test_user.id)
        assert preview["questions_count"] == 1
        assert preview["total_points"] == 3

    async with factory() as s:
        stats = await TestService(s).get_statistics(test_id, test_user.id)
        assert stats["questions_count"] == 1
        assert stats["exams_count"] == 0
        assert stats["times_used"] == 0


@pytest.mark.asyncio
async def test_other_user_cannot_edit_someone_elses_test_question(
    engine, test_user, second_user,
):
    from fastapi import HTTPException

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as s:
        test = await TestService(s).create_test(
            {"title": "Private Test", "test_type": "quiz", "visibility": "private"},
            owner_id=test_user.id,
        )
        test_id = test.id
        await s.commit()

    async with factory() as s:
        with pytest.raises(HTTPException):
            await TestService(s).create_question_in_test(
                test_id, {"title": "Hack", "question_type": "single_choice"},
                second_user.id,
            )
