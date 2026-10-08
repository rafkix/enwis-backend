from __future__ import annotations

from pydantic import BaseModel, Field

# ── Allowed values ──────────────────────────────────────────────────

ALLOWED_QUESTION_TYPES = (
    "multiple_choice",
    "multiple_select",
    "true_false",
    "short_answer",
    "essay",
    "numeric",
)

ALLOWED_DIFFICULTY_LEVELS = ("easy", "medium", "hard")

ALLOWED_PROVIDERS = ("gemini", "openrouter", "deepseek", "openai", "ollama", "groq")

ALLOWED_LANGUAGES = ("en", "uz", "ru", "tr", "de", "fr", "es", "ar", "zh", "ko", "ja")


# ── Request ─────────────────────────────────────────────────────────


class AIQuestionGenerateRequest(BaseModel):
    provider: str = Field("groq", description="AI provider name")
    subject: str = Field(..., min_length=1, max_length=255, description="Subject area")
    topic: str = Field(..., min_length=1, max_length=255, description="Specific topic")
    language: str = Field("en", max_length=10, description="Question language")
    difficulty: str = Field("medium", description="Difficulty level")
    question_count: int = Field(10, ge=1, le=100, description="Number of questions")
    question_type: str = Field("multiple_choice", description="Question type")


# ── Single question (AI raw output) ────────────────────────────────


class AIQuestionOption(BaseModel):
    text: str
    is_correct: bool = False


class AIQuestionItem(BaseModel):
    title: str
    description: str = ""
    type: str = "multiple_choice"
    options: list[AIQuestionOption] = []
    correct_answers: list[str] = []
    explanation: str = ""
    difficulty: str = "medium"
    points: int = 1


class AIQuestionResponse(BaseModel):
    questions: list[AIQuestionItem]


# ── Provider info ──────────────────────────────────────────────────


class AIProviderInfo(BaseModel):
    name: str
    is_available: bool
