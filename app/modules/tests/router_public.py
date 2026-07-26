"""Public test discovery & practice-taking API — used exclusively by
test.enwis.uz.

Browsing (`/public/tests*`) needs no authentication. Taking a test
(`start/save/submit/result/attempts`) requires a logged-in user, but on
test.enwis.uz that login is Google or Telegram only (see
app/modules/auth) — never username+password, and never the
app.enwis.uz registration flow.

Test authoring/management (app.enwis.uz) lives entirely in
`router_management.py` — kept separate on purpose so a public,
unauthenticated visitor can never reach an owner-only action by path
guessing.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_active_user
from app.modules.auth.models import User
from app.modules.tests.practice_service import TestPracticeService
from app.modules.tests.router_common import (
    test_to_public_response,
    test_to_public_response_from_row,
)
from app.modules.tests.schemas import (
    TestCategoryResponse,
    TestPracticeSaveRequest,
    TestPracticeStartResponse,
    TestPracticeSubmitRequest,
    TestPublicListResponse,
    TestPublicResponse,
)
from app.modules.tests.service import TestService

router = APIRouter(prefix="/public/tests", tags=["Tests — Public (test.enwis.uz)"])


def get_test_service(db: AsyncSession = Depends(get_db)) -> TestService:
    return TestService(db)


def get_practice_service(db: AsyncSession = Depends(get_db)) -> TestPracticeService:
    return TestPracticeService(db)


# =====================================================================
# Static routes MUST be declared before /{slug} or /{test_id}, otherwise
# FastAPI will treat path segments like "trending"/"categories" as an id.
# =====================================================================


@router.get("", response_model=TestPublicListResponse)
async def list_public_tests(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    category: str | None = Query(None),
    difficulty: str | None = Query(None),
    subject: str | None = Query(None),
    language: str | None = Query(None),
    sort: str = Query("newest", pattern="^(newest|oldest|popular)$"),
    service: TestService = Depends(get_test_service),
):
    result = await service.list_public_tests(
        page=page,
        per_page=limit,
        search=search,
        category=category,
        difficulty=difficulty,
        subject=subject,
        language=language,
        sort=sort,
    )
    return TestPublicListResponse(
        items=[test_to_public_response_from_row(row) for row in result["items"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
        pages=result["pages"],
    )


@router.get("/trending", response_model=list[TestPublicResponse])
async def trending_tests(
    limit: int = Query(10, ge=1, le=50),
    service: TestService = Depends(get_test_service),
):
    tests = await service.list_trending_tests(limit)
    return [test_to_public_response(t) for t in tests]


@router.get("/popular", response_model=list[TestPublicResponse])
async def popular_tests(
    limit: int = Query(10, ge=1, le=50),
    service: TestService = Depends(get_test_service),
):
    tests = await service.list_popular_tests(limit)
    return [test_to_public_response(t) for t in tests]


@router.get("/recent", response_model=list[TestPublicResponse])
async def recent_tests(
    limit: int = Query(10, ge=1, le=50),
    service: TestService = Depends(get_test_service),
):
    tests = await service.list_recent_tests(limit)
    return [test_to_public_response(t) for t in tests]


@router.get("/recommended", response_model=list[TestPublicResponse])
async def recommended_tests(
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    tests = await service.list_recommended_tests(limit)
    return [test_to_public_response(t) for t in tests]


@router.get("/categories", response_model=list[TestCategoryResponse])
async def list_categories(
    service: TestService = Depends(get_test_service),
):
    return await service.list_categories()


# ── Favorites (test-taker side) ─────────────────────────────────────


@router.post("/{test_id}/favorite", status_code=204)
async def favorite_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    await service.favorite_test(uuid.UUID(test_id), user.id)


@router.delete("/{test_id}/favorite", status_code=204)
async def unfavorite_test(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    await service.unfavorite_test(uuid.UUID(test_id), user.id)


# ── Practice — taking a test (test.enwis.uz, Google/Telegram login) ──


@router.post("/{test_id}/start", response_model=TestPracticeStartResponse)
async def start_practice(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestPracticeService = Depends(get_practice_service),
):
    return await service.start(uuid.UUID(test_id), user.id)


@router.post("/{test_id}/save")
async def save_practice(
    test_id: str,
    payload: TestPracticeSaveRequest,
    user: User = Depends(get_active_user),
    service: TestPracticeService = Depends(get_practice_service),
):
    return await service.save(
        payload.attempt_id,
        user.id,
        [a.model_dump() for a in payload.answers],
    )


@router.post("/{test_id}/submit")
async def submit_practice(
    test_id: str,
    payload: TestPracticeSubmitRequest,
    user: User = Depends(get_active_user),
    service: TestPracticeService = Depends(get_practice_service),
):
    return await service.submit(
        payload.attempt_id,
        user.id,
        [a.model_dump() for a in payload.answers],
    )


@router.get("/{test_id}/result")
async def practice_result(
    test_id: str,
    attempt_id: str = Query(...),
    user: User = Depends(get_active_user),
    service: TestPracticeService = Depends(get_practice_service),
):
    return await service.get_result(uuid.UUID(attempt_id), user.id)


@router.get("/{test_id}/attempts")
async def list_practice_attempts(
    test_id: str,
    user: User = Depends(get_active_user),
    service: TestPracticeService = Depends(get_practice_service),
):
    return await service.list_attempts(uuid.UUID(test_id), user.id)


@router.get("/my-results")
async def my_results(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_active_user),
    service: TestPracticeService = Depends(get_practice_service),
):
    """Foydalanuvchining BARCHA testlar bo'yicha natijalar tarixi —
    profil sahifasidagi 'Mening natijalarim'."""
    return await service.list_my_results(user.id, page=page, per_page=limit)


@router.get("/favorites", response_model=TestPublicListResponse)
async def list_favorites(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_active_user),
    service: TestService = Depends(get_test_service),
):
    """Foydalanuvchi 'yurak' bosgan testlar — 'Sevimlilarim' sahifasi."""
    result = await service.list_favorites(user.id, page=page, per_page=limit)
    return TestPublicListResponse(
        items=[test_to_public_response(t) for t in result["items"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
        pages=result["pages"],
    )


# =====================================================================
# Dynamic /{slug} routes — MUST stay after every static path above,
# or FastAPI will swallow those paths as {slug}.
# =====================================================================


@router.get("/{slug}", response_model=TestPublicResponse)
async def get_public_test(
    slug: str,
    service: TestService = Depends(get_test_service),
):
    test = await service.get_public_test(slug)
    return test_to_public_response(test)


@router.get("/{slug}/statistics")
async def get_public_test_statistics(
    slug: str,
    service: TestService = Depends(get_test_service),
):
    return await service.get_public_test_statistics(slug)


# NOTE: Test-level Exam attempt/participant endpoints were intentionally
# NOT added here — per the product spec, official Exam registration and
# attempts live exclusively under app.modules.exams
# (Exam -> Registration -> Attempt -> Result, exams.enwis.uz).
# This router only covers self-serve "practice" tests taken on
# test.enwis.uz.
