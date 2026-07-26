"""Test authoring & management API — used exclusively by app.enwis.uz.

Everything here requires an authenticated, active owner account. This is
where a user creates a test, adds/edits/reorders questions, generates
questions with AI, imports/exports question banks, configures settings,
and publishes/archives the test.

Public browsing and test-taking (test.enwis.uz) lives in
`router_public.py` — kept fully separate so the two front-ends never
share ambiguous paths or accidentally leak owner-only actions.
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_active_user
from app.modules.auth.models import User
from app.modules.questions.schemas import QuestionCreate, QuestionResponse, QuestionUpdate
from app.modules.tests.router_common import question_to_response, test_to_response
from app.modules.tests.schemas import (
    TestAIQuestionGenerateRequest,
    TestCreate,
    TestListResponse,
    TestQuestionOrder,
    TestResponse,
    TestSettingsUpdate,
    TestShareResponse,
    TestUpdate,
)
from app.modules.tests.service import TestService, TestSettingsNotFoundException

router = APIRouter(prefix="/tests", tags=["Tests — Management (app.enwis.uz)"])


def get_test_service(db: AsyncSession = Depends(get_db)) -> TestService:
    return TestService(db)


# =====================================================================
# Static routes MUST be declared before /{test_id}, otherwise FastAPI
# will treat path segments like "ai" as a UUID.
# =====================================================================


@router.get("/my", response_model=TestListResponse)
async def list_my_tests(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    search: str | None = Query(None),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    return await service.list_tests(
        owner_id=user.id,
        page=page,
        per_page=limit,
        status_filter=status,
        search=search,
    )


@router.post("", response_model=TestResponse, status_code=201)
async def create_test(
    payload: TestCreate,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    test = await service.create_test(payload.model_dump(), owner_id=user.id)
    return test_to_response(test)


@router.get("/ai/providers")
async def list_ai_providers():
    from app.modules.ai.service import AIService

    return AIService.list_providers()


@router.get("/import-template/excel")
async def download_import_template_excel(
    user: User = Depends(get_active_user),
):
    """Bo'sh, tayyor Excel shabloni — HALI TEST YARATILMAGAN bo'lsa ham
    yuklab olinadi (masalan 'Excel orqali yuklash' bo'limidagi
    'Namunani yuklab olish' tugmasi). Ustunlar bo'yicha dropdown
    validatsiya (Question Type) ham o'rnatilgan."""
    from app.modules.questions.import_utils import generate_import_template

    buf = generate_import_template()
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="enwis_savollar_shabloni.xlsx"'},
    )


@router.get("/import-template/csv")
async def download_import_template_csv(
    user: User = Depends(get_active_user),
):
    """Bo'sh CSV shabloni — Excel shabloni bilan bir xil ustunlar."""
    import csv
    import io

    from app.modules.questions.import_utils import TEMPLATE_HEADERS

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(TEMPLATE_HEADERS)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="enwis_savollar_shabloni.csv"'},
    )


# =====================================================================
# Dynamic /{test_id} routes — everything above this line must stay
# above it, or FastAPI will swallow those paths as {test_id}.
# =====================================================================


@router.get("/{test_id}", response_model=TestResponse)
async def get_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    test = await service.get_test(uuid.UUID(test_id), user.id)
    return test_to_response(test)


@router.put("/{test_id}", response_model=TestResponse)
@router.patch("/{test_id}", response_model=TestResponse)
async def update_test(
    test_id: str,
    payload: TestUpdate,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    test = await service.update_test(
        uuid.UUID(test_id),
        {k: v for k, v in payload.model_dump().items() if v is not None},
        user.id,
    )
    return test_to_response(test)


@router.delete("/{test_id}", status_code=204)
async def delete_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    await service.delete_test(uuid.UUID(test_id), user.id)


# ── Test lifecycle ────────────────────────────────────────────────────


@router.post("/{test_id}/publish", response_model=TestResponse)
async def publish_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    test = await service.publish_test(uuid.UUID(test_id), user.id)
    return test_to_response(test)


@router.post("/{test_id}/unpublish", response_model=TestResponse)
async def unpublish_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    test = await service.unpublish_test(uuid.UUID(test_id), user.id)
    return test_to_response(test)


@router.post("/{test_id}/archive", response_model=TestResponse)
async def archive_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    test = await service.archive_test(uuid.UUID(test_id), user.id)
    return test_to_response(test)


@router.post("/{test_id}/duplicate", status_code=201, response_model=TestResponse)
async def duplicate_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    test = await service.duplicate_test(uuid.UUID(test_id), user.id)
    return test_to_response(test)


@router.post("/{test_id}/share", response_model=TestShareResponse)
async def share_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    """Flips visibility to public and returns the test.enwis.uz URL —
    this is the bridge between the two front-ends."""
    return await service.share_test(uuid.UUID(test_id), user.id)


@router.get("/{test_id}/preview")
async def preview_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    return await service.preview_test(uuid.UUID(test_id), user.id)


@router.get("/{test_id}/statistics")
async def test_statistics(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    return await service.get_statistics(uuid.UUID(test_id), user.id)


# ── Questions (managed entirely inside Test — no standalone /questions API) ──


@router.get("/{test_id}/questions", response_model=list[QuestionResponse])
async def list_questions(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    questions = await service.list_questions_full(uuid.UUID(test_id), user.id)
    return [question_to_response(q) for q in questions]


@router.post("/{test_id}/questions", status_code=201, response_model=QuestionResponse)
async def create_question(
    test_id: str,
    payload: QuestionCreate,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    question = await service.create_question_in_test(
        uuid.UUID(test_id),
        payload.model_dump(),
        user.id,
    )
    return question_to_response(question)


@router.patch("/{test_id}/questions/reorder")
@router.put("/{test_id}/questions/reorder")
async def reorder_questions(
    test_id: str,
    payload: TestQuestionOrder,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    await service.reorder_questions(uuid.UUID(test_id), payload.question_ids, user.id)
    return {"success": True}


@router.patch("/{test_id}/questions/{question_id}", response_model=QuestionResponse)
async def update_question(
    test_id: str,
    question_id: str,
    payload: QuestionUpdate,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    question = await service.update_question_in_test(
        uuid.UUID(test_id),
        uuid.UUID(question_id),
        {k: v for k, v in payload.model_dump().items() if v is not None},
        user.id,
    )
    return question_to_response(question)


@router.delete("/{test_id}/questions/{question_id}", status_code=204)
async def delete_question(
    test_id: str,
    question_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    await service.delete_question_from_test(
        uuid.UUID(test_id),
        uuid.UUID(question_id),
        user.id,
    )


# ── AI (question generation & assistance — nested under Tests) ─────


@router.post("/{test_id}/questions/ai")
async def ai_generate_questions(
    test_id: str,
    payload: TestAIQuestionGenerateRequest,
    user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate questions via a configurable AI provider and attach them
    to the selected Test (PRO/PREMIUM only)."""
    from app.modules.ai.schemas import AIQuestionGenerateRequest
    from app.modules.ai.service import AIService

    ai_svc = AIService(db)
    return await ai_svc.generate_questions(
        request=AIQuestionGenerateRequest(
            provider=payload.provider,
            subject=payload.subject,
            topic=payload.topic,
            language=payload.language,
            difficulty=payload.difficulty,
            question_count=payload.question_count,
            question_type=payload.question_type,
        ),
        test_id=uuid.UUID(test_id),
        user=user,
    )


@router.post("/{test_id}/questions/{question_id}/ai/improve")
async def ai_improve_question(
    test_id: str,
    question_id: str,
    language: str = Query("en"),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    """AI orqali savol matnini aniqroq/pedagogik jihatdan yaxshilash
    bo'yicha taklif oladi. Natija avtomatik saqlanmaydi — frontend
    ko'rsatib, foydalanuvchi tasdiqlasa alohida
    PATCH /{test_id}/questions/{question_id} bilan saqlanadi."""
    from app.modules.exams.ai import improve_question

    questions = await service.list_questions_full(uuid.UUID(test_id), user.id)
    question = next((q for q in questions if str(q.id) == question_id), None)
    if not question:
        raise HTTPException(404, "Question not found in this test")
    return await improve_question(question.title, language)


@router.post("/{test_id}/questions/{question_id}/ai/translate")
async def ai_translate_question(
    test_id: str,
    question_id: str,
    target_language: str = Query(..., description="Masalan: 'ru', 'en', 'uz'"),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    from app.modules.exams.ai import translate_question

    questions = await service.list_questions_full(uuid.UUID(test_id), user.id)
    question = next((q for q in questions if str(q.id) == question_id), None)
    if not question:
        raise HTTPException(404, "Question not found in this test")
    return await translate_question(question.title, target_language)


@router.post("/{test_id}/questions/{question_id}/ai/explain")
async def ai_explain_answer(
    test_id: str,
    question_id: str,
    language: str = Query("en"),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    from app.modules.exams.ai import explain_answer

    questions = await service.list_questions_full(uuid.UUID(test_id), user.id)
    question = next((q for q in questions if str(q.id) == question_id), None)
    if not question:
        raise HTTPException(404, "Question not found in this test")
    return await explain_answer(question.title, question.correct_answer or "", language)


# ── Import ───────────────────────────────────────────────────────────


@router.post("/{test_id}/import/json/preview")
async def preview_import_json(
    test_id: str,
    payload: list[QuestionCreate],
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    return await service.preview_import_json(
        uuid.UUID(test_id),
        [q.model_dump() for q in payload],
        user.id,
    )


@router.post("/{test_id}/import/excel/preview")
async def preview_import_excel(
    test_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    content = await file.read()
    return await service.preview_import_excel(uuid.UUID(test_id), content, user.id)


@router.post("/{test_id}/import/csv/preview")
async def preview_import_csv(
    test_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    content = await file.read()
    return await service.preview_import_csv(uuid.UUID(test_id), content, user.id)


@router.post("/{test_id}/import/json", status_code=201)
async def import_json(
    test_id: str,
    payload: list[QuestionCreate],
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    questions = await service.import_questions_json(
        uuid.UUID(test_id),
        [q.model_dump() for q in payload],
        user.id,
    )
    return {"items": [question_to_response(q) for q in questions]}


@router.post("/{test_id}/import/excel", status_code=201)
async def import_excel(
    test_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    content = await file.read()
    return await service.import_questions_excel(uuid.UUID(test_id), content, user.id)


@router.post("/{test_id}/import/csv", status_code=201)
async def import_csv(
    test_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    content = await file.read()
    return await service.import_questions_csv(uuid.UUID(test_id), content, user.id)


# ── Export ───────────────────────────────────────────────────────────


@router.get("/{test_id}/export/json")
async def export_json(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    return await service.export_questions_json(uuid.UUID(test_id), user.id)


@router.get("/{test_id}/export/excel")
async def export_excel(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    buf = await service.export_questions_excel(uuid.UUID(test_id), user.id)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="test_{test_id}_questions.xlsx"'},
    )


@router.get("/{test_id}/export/csv")
async def export_csv(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    csv_text = await service.export_questions_csv(uuid.UUID(test_id), user.id)
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="test_{test_id}_questions.csv"'},
    )


# ── Settings ─────────────────────────────────────────────────────────


@router.get("/{test_id}/settings")
async def get_test_settings(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    settings = await service.get_settings(uuid.UUID(test_id), user.id)
    if not settings:
        raise TestSettingsNotFoundException()
    return {
        "id": settings.id,
        "test_id": settings.test_id,
        "negative_marking": settings.negative_marking,
        "auto_submit": settings.auto_submit,
        "result_visibility": settings.result_visibility,
        "certificate_enabled": settings.certificate_enabled,
    }


@router.put("/{test_id}/settings")
async def update_test_settings(
    test_id: str,
    payload: TestSettingsUpdate,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    settings = await service.update_settings(
        uuid.UUID(test_id),
        {k: v for k, v in payload.model_dump().items() if v is not None},
        user.id,
    )
    return {
        "id": settings.id,
        "test_id": settings.test_id,
        "negative_marking": settings.negative_marking,
        "auto_submit": settings.auto_submit,
        "result_visibility": settings.result_visibility,
        "certificate_enabled": settings.certificate_enabled,
    }
