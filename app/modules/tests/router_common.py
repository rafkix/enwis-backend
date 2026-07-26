"""Shared helpers used by both the management router (app.enwis.uz) and
the public router (test.enwis.uz). Keeping response builders in one place
avoids drift between the two surfaces.
"""

from app.modules.questions.schemas import QuestionResponse
from app.modules.tests.models import Test
from app.modules.tests.schemas import TestPublicResponse, TestResponse


def test_to_response(test: Test) -> TestResponse:
    return TestResponse(
        id=test.id,
        title=test.title,
        description=test.description,
        instructions=getattr(test, "instructions", None),
        cover_image=getattr(test, "cover_image", None),
        test_type=test.test_type,
        status=test.status,
        visibility=getattr(test, "visibility", "private"),
        shuffle_questions=getattr(test, "shuffle_questions", False),
        shuffle_answers=getattr(test, "shuffle_answers", False),
        show_result=getattr(test, "show_result", True),
        allow_review=getattr(test, "allow_review", True),
        negative_marking=getattr(test, "negative_marking", False),
        auto_submit=getattr(test, "auto_submit", True),
        certificate_enabled=bool(
            test.settings.certificate_enabled if getattr(test, "settings", None) else False
        ),
        publish_at=getattr(test, "publish_at", None),
        expire_at=getattr(test, "expire_at", None),
        owner_id=test.owner_id,
        questions_count=len(test.test_questions),
        created_at=test.created_at,
        updated_at=test.updated_at,
    )


def test_to_public_response(test: Test) -> TestPublicResponse:
    base = test_to_response(test)
    return TestPublicResponse(**base.model_dump(), slug=str(test.id))


def test_to_public_response_from_row(row: dict) -> TestPublicResponse:
    test = row["test"]
    return TestPublicResponse(
        id=test.id,
        title=test.title,
        description=test.description,
        instructions=getattr(test, "instructions", None),
        cover_image=getattr(test, "cover_image", None),
        test_type=test.test_type,
        status=test.status,
        visibility=test.visibility,
        shuffle_questions=test.shuffle_questions,
        shuffle_answers=test.shuffle_answers,
        show_result=test.show_result,
        allow_review=test.allow_review,
        negative_marking=test.negative_marking,
        auto_submit=test.auto_submit,
        certificate_enabled=False,
        publish_at=test.publish_at,
        expire_at=test.expire_at,
        owner_id=test.owner_id,
        questions_count=row["questions_count"],
        created_at=test.created_at,
        updated_at=test.updated_at,
        slug=str(test.id),
    )


def question_to_response(q) -> QuestionResponse:
    return QuestionResponse(
        id=q.id,
        title=q.title,
        description=q.description,
        question_type=q.question_type,
        difficulty=q.difficulty,
        score=q.score,
        explanation=q.explanation,
        correct_answer=q.correct_answer,
        visibility=q.visibility,
        status=q.status,
        owner_id=q.owner_id,
        category_id=q.category_id,
        question_bank_id=q.question_bank_id,
        category=None,
        choices=[
            {
                "id": c.id,
                "content": c.content,
                "is_correct": c.is_correct,
                "order": getattr(c, "order", 0),
            }
            for c in q.choices
        ],
        tags=[],
        attachments=[],
        created_at=q.created_at,
        updated_at=q.updated_at,
    )

