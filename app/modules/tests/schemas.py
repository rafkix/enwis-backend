from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TestCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    instructions: str | None = None
    cover_image: str | None = None
    test_type: str = Field(..., min_length=1, max_length=50)
    visibility: str = "private"
    shuffle_questions: bool = False
    shuffle_answers: bool = False
    show_result: bool = True
    allow_review: bool = True
    negative_marking: bool = False
    auto_submit: bool = True
    publish_at: datetime | None = None
    expire_at: datetime | None = None


class TestUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    instructions: str | None = None
    cover_image: str | None = None
    test_type: str | None = Field(None, min_length=1, max_length=50)
    status: str | None = None
    visibility: str | None = None
    shuffle_questions: bool | None = None
    shuffle_answers: bool | None = None
    show_result: bool | None = None
    allow_review: bool | None = None
    negative_marking: bool | None = None
    auto_submit: bool | None = None
    publish_at: datetime | None = None
    expire_at: datetime | None = None


class TestResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    instructions: str | None
    cover_image: str | None
    test_type: str
    status: str
    visibility: str
    shuffle_questions: bool
    shuffle_answers: bool
    show_result: bool
    allow_review: bool
    negative_marking: bool
    auto_submit: bool
    certificate_enabled: bool = False
    publish_at: datetime | None
    expire_at: datetime | None
    owner_id: UUID
    questions_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TestListResponse(BaseModel):
    items: list[TestResponse]
    total: int
    page: int
    per_page: int
    pages: int


class TestPublicResponse(TestResponse):
    slug: str


class TestPublicListResponse(BaseModel):
    items: list[TestPublicResponse]
    total: int
    page: int
    per_page: int
    pages: int


class TestCategoryResponse(BaseModel):
    name: str
    count: int


class TestShareResponse(BaseModel):
    slug: str
    public_url: str


class TestQuestionAdd(BaseModel):
    question_id: UUID
    order: int | None = None
    points: int = 1
    required: bool = True


class TestQuestionResponse(BaseModel):
    id: UUID
    test_id: UUID
    question_id: UUID
    order: int
    points: int
    required: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TestQuestionUpdate(BaseModel):
    order: int | None = None
    points: int | None = None
    required: bool | None = None


class TestQuestionOrder(BaseModel):
    question_ids: list[UUID]


class TestSettingsUpdate(BaseModel):
    negative_marking: bool | None = None
    auto_submit: bool | None = None
    result_visibility: str | None = None
    certificate_enabled: bool | None = None


class TestAIGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=255)
    count: int = Field(5, ge=1, le=20)
    question_types: list[str] | None = None
    language: str = "en"


class TestAIQuestionGenerateRequest(BaseModel):
    provider: str = Field("gemini", description="AI provider name")
    subject: str = Field(..., min_length=1, max_length=255)
    topic: str = Field(..., min_length=1, max_length=255)
    language: str = Field("en", max_length=10)
    difficulty: str = Field("medium")
    question_count: int = Field(10, ge=1, le=100)
    question_type: str = Field("multiple_choice")


# NOTE: TestParticipantAdd/TestParticipantResponse were removed —
# participants/registration are handled exclusively via app.modules.exams.


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
    selected_option_id: UUID | None
    text_answer: str | None
    is_correct: bool | None
    points_earned: int

    model_config = {"from_attributes": True}


class AttemptResponse(BaseModel):
    id: UUID
    test_id: UUID
    user_id: UUID
    score: int | None
    total_points: int
    is_completed: bool
    started_at: datetime
    completed_at: datetime | None
    answers: list[AnswerResponse] = []

    model_config = {"from_attributes": True}


# ── Playable (practice attempts) ────────────────────────────────────


class TestPracticeAnswerItem(BaseModel):
    question_id: UUID
    selected_option_id: UUID | None = None
    text_answer: str | None = None


class TestPracticeSaveRequest(BaseModel):
    attempt_id: UUID
    answers: list[TestPracticeAnswerItem] = []


class TestPracticeSubmitRequest(BaseModel):
    attempt_id: UUID
    answers: list[TestPracticeAnswerItem] = []


class TestPracticeChoiceItem(BaseModel):
    """A choice as shown to the player — deliberately has no `is_correct`."""

    id: UUID
    content: str
    order: int


class TestPracticeAttachmentItem(BaseModel):
    id: UUID
    file_type: str
    file_url: str
    file_name: str


class TestPracticeQuestionItem(BaseModel):
    id: UUID
    title: str
    question_type: str
    points: int
    order: int
    choices: list[TestPracticeChoiceItem] = []
    attachments: list[TestPracticeAttachmentItem] = []


class TestPracticeStartResponse(BaseModel):
    id: UUID
    test_id: UUID
    status: str
    questions_count: int
    max_score: int
    started_at: datetime
    expires_at: datetime | None = None
    questions: list[TestPracticeQuestionItem]


# ── Rasch (1-parameter IRT) ─────────────────────────────────────────


class RaschCalibrateRequest(BaseModel):
    question_ids: list[UUID] | None = Field(
        default=None,
        description="Kalibrlanadigan savollar. Berilmasa — owner'ning "
        "barcha savollari kalibrlanadi.",
    )


class RaschCalibratedItem(BaseModel):
    question_id: UUID
    irt_b: float


class RaschCalibrateResponse(BaseModel):
    calibrated: int
    skipped: int
    n_responses: int
    n_persons: int = 0
    converged: bool
    iterations: int = 0
    items: list[RaschCalibratedItem]


class RaschGenerateTestRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    target_theta: float = Field(
        0.0, ge=-4, le=4,
        description="Maqsadli qobiliyat darajasi (logit shkala, taxminan "
        "-4..+4). 0 — o'rtacha, manfiy — pastroq, musbat — yuqoriroq.",
    )
    num_questions: int = Field(..., ge=1, le=200)
    question_bank_id: UUID | None = None
    category_id: UUID | None = None
    require_calibrated: bool = True
    min_gap: float = Field(
        0.0, ge=0,
        description="Tanlangan savollar qiyinliklari orasidagi minimal "
        "farq (logit). 0 — cheklovsiz, eng informativ savollar tanlanadi.",
    )


class RaschInformationPoint(BaseModel):
    theta: float
    information: float


class RaschGenerateTestResponse(BaseModel):
    test: TestResponse
    target_theta: float
    selected_question_ids: list[UUID]
    difficulty_spread: dict
    information_curve: list[RaschInformationPoint]


class QuestionAnalysisItem(BaseModel):
    """Classical test theory (CTT) item analysis for a single question,
    computed from real answer history (test_practice_answers +
    question_answers). Not to be confused with Rasch/IRT calibration
    (`irt_b`) — both are surfaced here side by side.
    """

    question_id: UUID
    title: str
    question_type: str
    difficulty: str
    irt_b: float | None = None
    irt_calibrated_at: datetime | None = None

    times_answered: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    correct_rate: float = 0.0  # p-value, percent

    # Point-biserial correlation between getting this item right and the
    # attempt's overall percentage. Roughly -1..1; None if there isn't
    # enough data (need at least one correct AND one incorrect answer,
    # with non-zero score variance) to compute it.
    discrimination: float | None = None

    # "ok" | "too_easy" | "too_hard" | "poor_discrimination" | "insufficient_data"
    flag: str = "insufficient_data"


class TestQuestionAnalysisResponse(BaseModel):
    test_id: UUID
    questions_count: int
    total_answers_considered: int
    items: list[QuestionAnalysisItem]


