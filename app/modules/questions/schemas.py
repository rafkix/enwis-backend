from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.questions.constants import DIFFICULTY_LEVELS, QUESTION_TYPE_CHOICES

# ── Category ───────────────────────────────────────────────────────


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: UUID | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    parent_id: UUID | None = None


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None
    children: list["CategoryResponse"] = []

    model_config = {"from_attributes": True}


# ── Tag ────────────────────────────────────────────────────────────


class TagResponse(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


# ── Question Bank ──────────────────────────────────────────────────


class QuestionBankCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    visibility: str = "private"


class QuestionBankUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    visibility: str | None = None


class QuestionBankResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    owner_id: UUID
    visibility: str
    questions_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Choice ─────────────────────────────────────────────────────────


class ChoiceCreate(BaseModel):
    content: str = Field(..., min_length=1)
    is_correct: bool = False
    order: int = 0


class ChoiceResponse(BaseModel):
    id: UUID
    content: str
    is_correct: bool
    order: int

    model_config = {"from_attributes": True}


# ── Attachment ─────────────────────────────────────────────────────


class AttachmentResponse(BaseModel):
    id: UUID
    file_type: str
    file_url: str
    file_name: str
    file_size: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Question ───────────────────────────────────────────────────────


class QuestionCreate(BaseModel):
    title: str = Field(..., min_length=1)
    description: str | None = None
    question_type: str = "single_choice"
    difficulty: str = "medium"
    score: int = 1
    explanation: str | None = None
    correct_answer: str | None = None
    visibility: str = "private"
    category_id: UUID | None = None
    question_bank_id: UUID | None = None
    tag_ids: list[UUID] = []
    choices: list[ChoiceCreate] = []

    @field_validator("question_type")
    @classmethod
    def _valid_question_type(cls, v: str) -> str:
        if v not in QUESTION_TYPE_CHOICES:
            raise ValueError(
                f"Invalid question_type '{v}'. Must be one of: {', '.join(QUESTION_TYPE_CHOICES)}"
            )
        return v

    @field_validator("difficulty")
    @classmethod
    def _valid_difficulty(cls, v: str) -> str:
        if v not in DIFFICULTY_LEVELS:
            raise ValueError(
                f"Invalid difficulty '{v}'. Must be one of: {', '.join(DIFFICULTY_LEVELS)}"
            )
        return v

    @field_validator("choices")
    @classmethod
    def _valid_choices(cls, v: list["ChoiceCreate"], info) -> list["ChoiceCreate"]:
        qtype = info.data.get("question_type")
        if qtype in ("single_choice", "image"):
            if len(v) < 2:
                raise ValueError(
                    f"'{qtype}' questions need at least 2 choices"
                )
            correct_count = sum(1 for c in v if c.is_correct)
            if correct_count != 1:
                raise ValueError(
                    f"'{qtype}' questions need exactly one correct choice, found {correct_count}"
                )
        return v


class QuestionUpdate(BaseModel):
    title: str | None = Field(None, min_length=1)
    description: str | None = None
    question_type: str | None = None
    difficulty: str | None = None
    score: int | None = None
    explanation: str | None = None
    visibility: str | None = None
    status: str | None = None
    category_id: UUID | None = None
    question_bank_id: UUID | None = None
    tag_ids: list[UUID] | None = None
    choices: list[ChoiceCreate] | None = None


class QuestionResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    question_type: str
    difficulty: str
    score: int
    explanation: str | None
    correct_answer: str | None = None
    visibility: str
    status: str
    owner_id: UUID
    category_id: UUID | None
    question_bank_id: UUID | None
    category: CategoryResponse | None = None
    choices: list[ChoiceResponse] = []
    tags: list[TagResponse] = []
    attachments: list[AttachmentResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuestionListResponse(BaseModel):
    id: UUID
    title: str
    question_type: str
    difficulty: str
    score: int
    status: str
    visibility: str
    category_id: UUID | None
    question_bank_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Bulk ───────────────────────────────────────────────────────────


class BulkQuestionCreate(BaseModel):
    questions: list[QuestionCreate]


class BulkMoveCopy(BaseModel):
    question_ids: list[UUID]
    target_bank_id: UUID


class BulkDelete(BaseModel):
    question_ids: list[UUID]


# ── Search / Filter ────────────────────────────────────────────────


class QuestionFilterParams(BaseModel):
    question_type: str | None = None
    difficulty: str | None = None
    status: str | None = None
    visibility: str | None = None
    category_id: UUID | None = None
    question_bank_id: UUID | None = None
    tag_id: UUID | None = None
    owner_id: UUID | None = None
    search: str | None = None
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)


# ── Statistics ─────────────────────────────────────────────────────


class QuestionStatistics(BaseModel):
    total_attempts: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    accuracy: float = 0.0
    avg_time_seconds: float | None = None
    used_in_exams: int = 0


# ── Question Type Metadata ────────────────────────────────────────


class QuestionTypeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    has_options: bool = True
    has_correct_answer: bool = True
    has_image: bool = False
    has_video: bool = False
    max_options: int = Field(6, ge=2, le=20)
    min_options: int = Field(2, ge=0, le=20)
    sort_order: int = 0


class QuestionTypeUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    has_options: bool | None = None
    has_correct_answer: bool | None = None
    has_image: bool | None = None
    has_video: bool | None = None
    max_options: int | None = Field(None, ge=2, le=20)
    min_options: int | None = Field(None, ge=0, le=20)
    is_active: bool | None = None
    sort_order: int | None = None


class QuestionTypeResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: str | None
    has_options: bool
    has_correct_answer: bool
    has_image: bool
    has_video: bool
    max_options: int
    min_options: int
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuestionTypeListResponse(BaseModel):
    items: list[QuestionTypeResponse]
    total: int


class ImproveQuestionRequest(BaseModel):
    question_text: str = Field(..., min_length=1)
    language: str = "en"


class TranslateQuestionRequest(BaseModel):
    text: str = Field(..., min_length=1)
    target_language: str


class ExplainAnswerRequest(BaseModel):
    question_text: str = Field(..., min_length=1)
    correct_answer: str = Field(..., min_length=1)
    language: str = "en"
