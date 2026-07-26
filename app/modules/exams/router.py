import uuid

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import get_active_user, require_roles
from app.modules.auth.models import User
from app.modules.exams.attempt_dependencies import get_attempt_service
from app.modules.exams.attempt_service import AttemptService
from app.modules.exams.dependencies import get_exam_service
from app.modules.exams.schemas import (
    AttemptDetail,
    AttemptStartResponse,
    ExamCreate,
    ExamParticipantAdd,
    ExamParticipantResponse,
    ExamResponse,
    ExamUpdate,
    LeaderboardResponse,
    ManualGradeRequest,
    PaginatedResponse,
    ResultResponse,
    ResumeResponse,
    SaveAnswersRequest,
    SubmitResponse,
)
from app.modules.exams.service import ExamService

router = APIRouter(prefix="/exams", tags=["Exams"])


# ── Exam CRUD ─────────────────────────────────────────────────────────


@router.get("", response_model=PaginatedResponse)
async def list_exams(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    search: str | None = Query(None),
    user: User = Depends(get_active_user),
    service: ExamService = Depends(get_exam_service),
):
    return await service.list_exams(
        owner_id=user.id, page=page, per_page=per_page,
        status_filter=status, search=search,
    )


@router.post("", response_model=ExamResponse, status_code=201)
async def create_exam(
    payload: ExamCreate,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ExamService = Depends(get_exam_service),
):
    exam = await service.create_exam(
        payload.model_dump(), owner_id=user.id
    )
    return _exam_to_response(exam)


@router.get("/{exam_id}", response_model=ExamResponse)
async def get_exam(
    exam_id: str,
    user: User = Depends(get_active_user),
    service: ExamService = Depends(get_exam_service),
):
    exam = await service.get_exam(uuid.UUID(exam_id), user.id)
    return _exam_to_response(exam)


@router.put("/{exam_id}", response_model=ExamResponse)
async def update_exam(
    exam_id: str,
    payload: ExamUpdate,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ExamService = Depends(get_exam_service),
):
    exam = await service.update_exam(
        uuid.UUID(exam_id),
        {k: v for k, v in payload.model_dump().items() if v is not None},
        user.id,
    )
    return _exam_to_response(exam)


@router.delete("/{exam_id}", status_code=204)
async def delete_exam(
    exam_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ExamService = Depends(get_exam_service),
):
    await service.delete_exam(uuid.UUID(exam_id), user.id)


# ── Exam Publishing ─────────────────────────────────────────────────


@router.post("/{exam_id}/publish", response_model=ExamResponse)
async def publish_exam(
    exam_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ExamService = Depends(get_exam_service),
):
    exam = await service.publish_exam(uuid.UUID(exam_id), user.id)
    return _exam_to_response(exam)


@router.post("/{exam_id}/archive", response_model=ExamResponse)
async def archive_exam(
    exam_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ExamService = Depends(get_exam_service),
):
    exam = await service.archive_exam(uuid.UUID(exam_id), user.id)
    return _exam_to_response(exam)


@router.post(
    "/{exam_id}/duplicate", status_code=201, response_model=ExamResponse
)
async def duplicate_exam(
    exam_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ExamService = Depends(get_exam_service),
):
    exam = await service.duplicate_exam(uuid.UUID(exam_id), user.id)
    return _exam_to_response(exam)


# ── Participants ────────────────────────────────────────────────────


@router.post("/{exam_id}/participants", status_code=201)
async def add_participant(
    exam_id: str,
    payload: ExamParticipantAdd,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ExamService = Depends(get_exam_service),
):
    p = await service.add_participant(
        uuid.UUID(exam_id), payload.user_id, user.id
    )
    return ExamParticipantResponse(
        id=p.id, exam_id=p.exam_id,
        user_id=p.user_id, created_at=p.created_at,
    )


@router.get("/{exam_id}/participants")
async def list_participants(
    exam_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ExamService = Depends(get_exam_service),
):
    participants = await service.list_participants(
        uuid.UUID(exam_id), user.id
    )
    return {
        "items": [
            ExamParticipantResponse(
                id=p.id, exam_id=p.exam_id,
                user_id=p.user_id, created_at=p.created_at,
            )
            for p in participants
        ]
    }


@router.delete(
    "/{exam_id}/participants/{participant_id}", status_code=204
)
async def remove_participant(
    exam_id: str,
    participant_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ExamService = Depends(get_exam_service),
):
    await service.remove_participant(
        uuid.UUID(exam_id), uuid.UUID(participant_id), user.id
    )


# NOTE: /ai/improve, /ai/translate, /ai/explain were moved to
# app.modules.questions.router — they operate on Question content
# (improve wording / translate / explain an answer), not exam
# scheduling, so they belong in the questions module. Use
# POST /questions/ai/improve, /questions/ai/translate,
# /questions/ai/explain instead.


# ── Helpers ──────────────────────────────────────────────────────────


def _exam_to_response(exam) -> ExamResponse:
    test = exam.test
    questions_count = 0
    test_title = None
    if test:
        test_title = test.title
        if hasattr(test, "test_questions"):
            questions_count = len(test.test_questions)

    status_val = (
        exam.status.value
        if hasattr(exam.status, "value")
        else exam.status
    )
    vis_val = (
        exam.visibility.value
        if hasattr(exam.visibility, "value")
        else exam.visibility
    )

    return ExamResponse(
        id=exam.id,
        title=exam.title,
        description=exam.description,
        test_id=exam.test_id,
        test_title=test_title,
        status=status_val,
        visibility=vis_val,
        start_time=exam.start_time,
        end_time=exam.end_time,
        duration_minutes=exam.duration_minutes,
        passing_score=exam.passing_score,
        max_attempts=exam.max_attempts,
        has_password=bool(getattr(exam, "password_hash", None)),
        owner_id=exam.owner_id,
        questions_count=questions_count,
        attempts_count=len(exam.attempts),
        avg_score=0.0,
        created_at=exam.created_at,
        updated_at=exam.updated_at,
    )


# ── Attempt Lifecycle ───────────────────────────────────────────


@router.post(
    "/{exam_id}/start",
    response_model=AttemptStartResponse,
    status_code=201,
    summary="Start a new exam attempt",
)
async def start_attempt(
    exam_id: str,
    user: User = Depends(get_active_user),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.start_attempt(uuid.UUID(exam_id), user.id)


@router.get(
    "/{attempt_id}/resume",
    response_model=ResumeResponse,
    summary="Resume an in-progress attempt",
)
async def resume_attempt(
    attempt_id: str,
    user: User = Depends(get_active_user),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.resume_attempt(uuid.UUID(attempt_id), user.id)


@router.get(
    "/{attempt_id}/questions",
    summary="Get questions for an in-progress attempt (answer key stripped)",
)
async def get_attempt_questions(
    attempt_id: str,
    user: User = Depends(get_active_user),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.get_attempt_questions(uuid.UUID(attempt_id), user.id)


@router.post(
    "/{attempt_id}/save",
    summary="Save answers during an active attempt",
)
async def save_answers(
    attempt_id: str,
    payload: SaveAnswersRequest,
    user: User = Depends(get_active_user),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.save_answers(
        uuid.UUID(attempt_id),
        user.id,
        [a.model_dump() for a in payload.answers],
    )


@router.post(
    "/{attempt_id}/submit",
    response_model=SubmitResponse,
    summary="Submit exam attempt for grading",
)
async def submit_attempt(
    attempt_id: str,
    payload: SaveAnswersRequest,
    user: User = Depends(get_active_user),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.submit_attempt(
        uuid.UUID(attempt_id),
        user.id,
        [a.model_dump() for a in payload.answers],
    )


@router.get(
    "/{attempt_id}/result",
    response_model=ResultResponse,
    summary="Get attempt result with grade breakdown",
)
async def get_result(
    attempt_id: str,
    user: User = Depends(get_active_user),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.get_result(uuid.UUID(attempt_id), user.id)


@router.get(
    "/{attempt_id}/review",
    response_model=AttemptDetail,
    summary="Review attempt answers with correct answers",
)
async def review_attempt(
    attempt_id: str,
    user: User = Depends(get_active_user),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.review_attempt(uuid.UUID(attempt_id), user.id)


@router.post(
    "/{attempt_id}/grade/{question_id}",
    summary="Manually grade a question (any type)",
)
async def manual_grade(
    attempt_id: str,
    question_id: str,
    payload: ManualGradeRequest,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.manual_grade(
        uuid.UUID(attempt_id),
        uuid.UUID(question_id),
        user.id,
        payload.points_earned,
        payload.feedback,
    )


@router.get(
    "/leaderboard/{exam_id}",
    response_model=LeaderboardResponse,
    summary="Get exam leaderboard",
)
async def leaderboard(
    exam_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_active_user),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.get_leaderboard(uuid.UUID(exam_id), limit)


@router.get(
    "/stats/{exam_id}",
    summary="Get exam attempt statistics",
)
async def exam_stats(
    exam_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.get_exam_stats(uuid.UUID(exam_id))


@router.get(
    "/my-attempts",
    response_model=PaginatedResponse,
    summary="List my attempts",
)
async def my_attempts(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(get_active_user),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.list_user_attempts(user.id, page, per_page)


@router.get(
    "/{exam_id}/attempts-list",
    response_model=PaginatedResponse,
    summary="List all attempts for an exam (exam owner)",
)
async def list_exam_attempts(
    exam_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: AttemptService = Depends(get_attempt_service),
):
    return await service.list_exam_attempts(uuid.UUID(exam_id), page, per_page, owner_id=user.id)
