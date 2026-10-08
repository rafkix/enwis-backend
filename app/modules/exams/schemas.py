from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Exam ──────────────────────────────────────────────────────────────

class ExamCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    test_id: UUID
    visibility: str = "private"
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: int | None = None
    passing_score: int = 60
    max_attempts: int = 3
    password: str | None = None


class ExamUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = None
    visibility: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: int | None = None
    passing_score: int | None = None
    max_attempts: int | None = None
    password: str | None = None


class ExamResponse(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    test_id: UUID
    test_title: str | None = None
    status: str
    visibility: str = "private"
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: int | None = None
    passing_score: int
    max_attempts: int
    has_password: bool = False
    owner_id: UUID
    questions_count: int = 0
    attempts_count: int = 0
    avg_score: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExamListResponse(BaseModel):
    id: UUID
    title: str
    test_id: UUID
    test_title: str | None = None
    status: str
    visibility: str = "private"
    start_time: datetime | None = None
    end_time: datetime | None = None
    questions_count: int = 0
    attempts_count: int = 0
    avg_score: float = 0.0
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Attempt ───────────────────────────────────────────────────────────

class SubmitAnswer(BaseModel):
    question_id: UUID
    selected_option_id: UUID | None = None
    selected_option_ids: list[UUID] | None = None
    text_answer: str | None = None


class AttemptSubmit(BaseModel):
    answers: list[SubmitAnswer]


class AnswerResponse(BaseModel):
    id: UUID
    question_id: UUID
    selected_option_id: UUID | None = None
    text_answer: str | None = None
    is_correct: bool | None = None
    points_earned: int = 0

    model_config = {"from_attributes": True}


class AttemptResponse(BaseModel):
    id: UUID
    exam_id: UUID
    user_id: UUID
    score: int | None = None
    total_points: int = 0
    is_completed: bool = False
    started_at: datetime
    completed_at: datetime | None = None
    answers: list[AnswerResponse] = []

    model_config = {"from_attributes": True}


# ── Participant ───────────────────────────────────────────────────────

class ExamParticipantAdd(BaseModel):
    user_id: UUID


class ExamParticipantResponse(BaseModel):
    id: UUID
    exam_id: UUID
    user_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Pagination ────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
    pages: int


# ── AI ────────────────────────────────────────────────────────────────

class GenerateQuestionsRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    count: int = Field(5, ge=1, le=50)
    question_types: list[str] | None = None
    language: str = "en"


# ── Attempt Lifecycle ─────────────────────────────────────────────

class SaveAnswerItem(BaseModel):
    question_id: UUID
    selected_option_id: UUID | None = None
    selected_option_ids: list[UUID] | None = None
    text_answer: str | None = None


class SaveAnswersRequest(BaseModel):
    answers: list[SaveAnswerItem] = Field(..., max_length=200)


class AttemptStartResponse(BaseModel):
    id: UUID
    exam_id: UUID
    user_id: UUID
    status: str
    score: int | None
    total_points: int
    started_at: datetime
    completed_at: datetime | None
    time_limit_minutes: int | None
    time_remaining_seconds: int | None

    model_config = {"from_attributes": True}


class AttemptSummary(BaseModel):
    id: UUID
    exam_id: UUID
    exam_title: str
    status: str
    score: int | None
    total_points: int
    percentage: float | None
    grade: str | None
    passed: bool | None
    started_at: datetime
    completed_at: datetime | None
    time_spent_seconds: int | None

    model_config = {"from_attributes": True}


class AnswerDetail(BaseModel):
    question_id: UUID
    question_text: str
    question_type: str
    points: int
    selected_option_text: str | None = None
    text_answer: str | None = None
    correct_answer: str | None = None
    correct_option_text: str | None = None
    is_correct: bool | None = None
    points_earned: int = 0
    order: int = 0
    explanation: str | None = None

    model_config = {"from_attributes": True}


class AttemptDetail(BaseModel):
    id: UUID
    exam_id: UUID
    exam_title: str
    user_id: UUID
    username: str | None
    status: str
    score: int | None
    total_points: int
    percentage: float | None
    grade: str | None
    passed: bool | None
    started_at: datetime
    completed_at: datetime | None
    time_spent_seconds: int | None
    answers: list[AnswerDetail] = []

    model_config = {"from_attributes": True}


class ResultResponse(BaseModel):
    attempt_id: UUID
    total_score: int
    max_score: int
    percentage: float
    grade: str | None
    correct_count: int
    wrong_count: int
    unanswered_count: int
    time_spent_seconds: int
    passed: bool
    graded_by: str | None
    graded_at: datetime | None

    model_config = {"from_attributes": True}


class SubmitResponse(BaseModel):
    attempt_id: UUID
    status: str
    score: int
    total_points: int
    percentage: float
    grade: str | None
    passed: bool
    correct_count: int
    wrong_count: int
    unanswered_count: int
    time_spent_seconds: int
    message: str


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: UUID
    username: str | None
    full_name: str | None
    avatar: str | None
    score: int
    total_points: int
    percentage: float
    time_spent_seconds: int
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class LeaderboardResponse(BaseModel):
    exam_id: UUID
    exam_title: str
    entries: list[LeaderboardEntry]
    total_entries: int


class ManualGradeRequest(BaseModel):
    points_earned: int = Field(..., ge=0)
    feedback: str | None = None


class ResumeResponse(BaseModel):
    attempt_id: UUID
    exam_id: UUID
    status: str
    score: int | None
    total_points: int
    started_at: datetime
    time_limit_minutes: int | None
    time_remaining_seconds: int | None
    saved_answers: list[SaveAnswerItem] = []
    questions_count: int = 0

    model_config = {"from_attributes": True}


class AttemptStats(BaseModel):
    total_attempts: int
    completed_attempts: int
    average_score: float
    average_percentage: float
    highest_score: int
    lowest_score: int
    pass_count: int
    fail_count: int
    pass_rate: float
