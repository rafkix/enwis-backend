from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import can_use_ai, get_ai_monthly_limit, get_user_plan_tier
from app.modules.ai.exceptions import (
    AIGenerationError,
    AINoApiKeyError,
    AIProviderNotFoundError,
    AIRateLimitError,
    AIResponseValidationError,
    AITimeoutError,
)
from app.modules.ai.providers.base import AIProvider
from app.modules.ai.providers.groq import GroqProvider
from app.modules.ai.providers.openrouter import OpenRouterProvider
from app.modules.ai.schemas import (
    ALLOWED_DIFFICULTY_LEVELS,
    ALLOWED_PROVIDERS,
    ALLOWED_QUESTION_TYPES,
    AIQuestionGenerateRequest,
)
from app.modules.ai.validators import validate_ai_response
from app.modules.auth.models import User
from app.modules.questions.models import (
    Choice,
    DifficultyLevel,
    QuestionType,
)
from app.modules.questions.models import (
    Question as QBQuestion,
)
from app.modules.tests.models import Test, TestQuestion

logger = logging.getLogger(__name__)

# Map AI question types to the DB QuestionType enum
_AI_TO_DB_QTYPE: dict[str, QuestionType] = {
    "multiple_choice": QuestionType.SINGLE_CHOICE,
    "multiple_select": QuestionType.SINGLE_CHOICE,
    "true_false": QuestionType.SINGLE_CHOICE,
    "short_answer": QuestionType.SHORT_ANSWER,
    "essay": QuestionType.SHORT_ANSWER,
    "numeric": QuestionType.SHORT_ANSWER,
}

_AI_TO_DB_DIFFICULTY: dict[str, DifficultyLevel] = {
    "easy": DifficultyLevel.EASY,
    "medium": DifficultyLevel.MEDIUM,
    "hard": DifficultyLevel.HARD,
}

logger = logging.getLogger(__name__)


# ── Provider registry ──────────────────────────────────────────────

_PROVIDER_MAP: dict[str, type[AIProvider]] = {
    "openrouter": OpenRouterProvider,
    "groq": GroqProvider,  # ← yangi
}


def _build_provider(name: str) -> AIProvider:
    """Instantiate the requested provider from its name."""
    name = name.lower().strip()

    if name == "openrouter":
        api_key = settings.OPENROUTER_API_KEY
        if not api_key:
            raise AINoApiKeyError("openrouter")
        return OpenRouterProvider(api_key=api_key)

    if name == "groq":
        api_key = settings.GROQ_API_KEY
        print(settings.GROQ_API_KEY)
        if not api_key:
            raise AINoApiKeyError("groq")
        return GroqProvider(api_key=api_key)

    if name in _PROVIDER_MAP:
        raise AINoApiKeyError(name)

    raise AIProviderNotFoundError(name)


# ── Prompt builder ─────────────────────────────────────────────────

_LANGUAGE_NAMES = {
    "en": "English",
    "uz": "Uzbek",
    "ru": "Russian",
    "tr": "Turkish",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "ar": "Arabic",
    "zh": "Chinese",
    "ko": "Korean",
    "ja": "Japanese",
}


def build_generation_prompt(
    subject: str,
    topic: str,
    question_count: int,
    question_type: str,
    difficulty: str,
    language: str,
) -> str:
    lang_name = _LANGUAGE_NAMES.get(language, language)

    options_hint = ""
    if question_type == "multiple_choice":
        options_hint = (
            "Each multiple_choice question MUST have exactly 4 options "
            "(A, B, C, D) with exactly ONE correct answer.\n"
        )
    elif question_type == "multiple_select":
        options_hint = (
            "Each multiple_select question MUST have 4-6 options "
            "with TWO OR MORE correct answers.\n"
        )
    elif question_type == "true_false":
        options_hint = (
            'Each true_false question MUST have exactly 2 options: "True" and "False", '
            "with exactly one correct.\n"
        )
    elif question_type == "numeric":
        options_hint = "Each numeric question requires a numeric correct_answers value.\n"

    return (
        f"You are a professional examination question writer.\n\n"
        f"Generate exactly {question_count} high-quality examination questions.\n\n"
        f"Subject: {subject}\n"
        f"Topic: {topic}\n"
        f"Language: {lang_name} ({language}) — ALL question text, options, and explanations "
        f"MUST be written in {lang_name}.\n"
        f"Difficulty: {difficulty}\n"
        f"Question type: {question_type}\n\n"
        f"{options_hint}\n"
        "Return ONLY valid JSON — no Markdown fences, no commentary outside the JSON.\n\n"
        'The JSON MUST be a single object with a top-level "questions" array:\n'
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "title": "The question text",\n'
        '      "description": "Optional additional context or stimulus",\n'
        f'      "type": "{question_type}",\n'
        '      "options": [\n'
        '        {"text": "Option A text", "is_correct": false},\n'
        '        {"text": "Option B text", "is_correct": true},\n'
        '        {"text": "Option C text", "is_correct": false},\n'
        '        {"text": "Option D text", "is_correct": false}\n'
        "      ],\n"
        '      "correct_answers": ["Option B text"],\n'
        '      "explanation": "Detailed explanation of why the correct answer is right",\n'
        f'      "difficulty": "{difficulty}",\n'
        '      "points": 1\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Requirements:\n"
        f"- Generate exactly {question_count} questions.\n"
        f'- Every question MUST have a non-empty "explanation" field.\n'
        f'- Every question MUST have "title", "type", "options", and "correct_answers".\n'
        f"- Questions must be factually accurate and educationally sound.\n"
        f"- Avoid trivial or ambiguous questions.\n"
        f'- Difficulty "{difficulty}" means: ' + _difficulty_description(difficulty)
    )


def _difficulty_description(difficulty: str) -> str:
    if difficulty == "easy":
        return "recall-based, straightforward, testing basic knowledge."
    if difficulty == "medium":
        return "application-level, requiring understanding of concepts."
    if difficulty == "hard":
        return "analysis/synthesis level, requiring deep understanding and critical thinking."
    return "moderate difficulty."


# ── Main service ───────────────────────────────────────────────────


class AIService:
    """Orchestrates AI question generation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Provider helpers
    # ------------------------------------------------------------------

    @staticmethod
    def list_providers() -> list[dict[str, Any]]:
        """Return all registered providers and whether they are configured."""
        result = []
        for name in ("gemini", "openrouter", "deepseek", "openai", "ollama", "groq"):
            available = False
            if name == "gemini":
                available = bool(settings.GEMINI_API_KEY)
            elif name == "openrouter":
                available = bool(settings.OPENROUTER_API_KEY)
            result.append({"name": name, "is_available": available})
        return result

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    async def generate_questions(
        self,
        request: AIQuestionGenerateRequest,
        test_id: uuid.UUID,
        user: User,
    ) -> dict[str, Any]:
        """Full pipeline: permission -> prompt -> AI -> validate -> persist."""
        start = time.monotonic()

        # 1. Validate inputs
        self._validate_request(request)

        # 2. Permission check + monthly AI limit
        tier = get_user_plan_tier(user.subscription_tier)
        override = user.ai_questions_quota_override
        # Admin tomonidan aniq quota belgilangan bo'lsa (va u 0 dan katta yoki
        # cheksiz bo'lsa), bu tier'ning ai_generation cheklovidan ustun turadi —
        # aks holda FREE foydalanuvchiga individual ruxsat berib bo'lmas edi.
        override_grants_access = override is not None and override != 0
        if not can_use_ai(tier) and not override_grants_access:
            raise HTTPException(
                403,
                "AI savol generatsiyasi sizning tarifingizda mavjud emas. "
                "Teacher, Pro yoki Premium tarifiga o'ting.",
            )

        # Oylik limitni tekshir va hisoblagichni yangilash.
        # Admin har bir foydalanuvchi uchun individual quota belgilagan
        # bo'lsa (ai_questions_quota_override), u tier standartidan ustun
        # turadi: None -> tier bo'yicha, -1 -> cheksiz, N -> aniq son.
        monthly_limit = override if override is not None else get_ai_monthly_limit(tier)
        if monthly_limit != -1:
            # Oy boshi tekshiruvi — yangi oy bo'lsa hisoblagichni reset qil
            now = datetime.now(UTC)
            reset_at = user.ai_questions_reset_at
            if reset_at is None or reset_at.year != now.year or reset_at.month != now.month:
                user.ai_questions_used = 0
                user.ai_questions_reset_at = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            remaining = monthly_limit - user.ai_questions_used
            needed = request.question_count
            if remaining <= 0:
                raise HTTPException(
                    429,
                    f"Oylik AI limit tugadi ({monthly_limit} ta). "
                    "Keyingi oyda yoki yuqori tarifga o'tib davom eting.",
                )
            if needed > remaining:
                raise HTTPException(
                    429,
                    f"So'ralgan savol soni ({needed}) oylik qolgan limitdan "
                    f"({remaining}) ko'p. Kamroq so'rang yoki tarifni yangilang.",
                )

        # 3. Verify test ownership & status
        test = await self._get_test(test_id, user.id)

        # 4. Build prompt
        prompt = build_generation_prompt(
            subject=request.subject,
            topic=request.topic,
            question_count=request.question_count,
            question_type=request.question_type,
            difficulty=request.difficulty,
            language=request.language,
        )

        # 5. Call AI provider
        provider = _build_provider(request.provider)
        try:
            raw_questions = await provider.generate(prompt)
        except httpx.TimeoutException:
            logger.warning(
                "AI provider timeout",
                extra={
                    "provider": request.provider,
                    "user_id": str(user.id),
                    "test_id": str(test_id),
                },
            )
            raise AITimeoutError() from None
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429:
                logger.warning(
                    "AI provider rate limited",
                    extra={
                        "provider": request.provider,
                        "user_id": str(user.id),
                    },
                )
                raise AIRateLimitError() from None
            logger.error(
                "AI provider HTTP error",
                extra={
                    "provider": request.provider,
                    "status": status_code,
                    "user_id": str(user.id),
                },
            )
            raise AIGenerationError(f"AI provider returned HTTP {status_code}") from None
        except httpx.HTTPError as exc:
            logger.error(
                "AI provider network error",
                extra={"provider": request.provider, "user_id": str(user.id)},
            )
            raise AIGenerationError(
                f"Network error communicating with AI provider: {exc}"
            ) from None
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "AI response parse error",
                extra={"provider": request.provider, "user_id": str(user.id)},
            )
            raise AIResponseValidationError(str(exc)) from None

        # 6. Validate AI output
        validated = validate_ai_response(raw_questions, expected_count=request.question_count)

        # 7. Persist in a transaction
        created = await self._persist_questions(test, validated, user.id)

        # 8. Increment AI usage counter (limit != -1 bo'lganda)
        if monthly_limit != -1:
            user.ai_questions_used += len(created)
            await self.db.commit()

        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "AI generation completed",
            extra={
                "user_id": str(user.id),
                "test_id": str(test_id),
                "provider": request.provider,
                "question_count": len(created),
                "duration_ms": duration_ms,
                "success": True,
            },
        )

        return {
            "questions": created,
            "provider": request.provider,
            "count": len(created),
            "duration_ms": duration_ms,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_request(request: AIQuestionGenerateRequest) -> None:
        if request.provider not in ALLOWED_PROVIDERS:
            raise AIProviderNotFoundError(request.provider)
        if request.question_type not in ALLOWED_QUESTION_TYPES:
            raise AIResponseValidationError(
                f"Invalid question_type '{request.question_type}'. "
                f"Allowed: {', '.join(ALLOWED_QUESTION_TYPES)}"
            )
        if request.difficulty not in ALLOWED_DIFFICULTY_LEVELS:
            raise AIResponseValidationError(
                f"Invalid difficulty '{request.difficulty}'. "
                f"Allowed: {', '.join(ALLOWED_DIFFICULTY_LEVELS)}"
            )

    async def _get_test(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> Test:
        result = await self.db.execute(
            select(Test).where(Test.id == test_id, Test.owner_id == owner_id)
        )
        test = result.scalar_one_or_none()
        if not test:
            raise HTTPException(404, "Test not found")
        if test.status == "active":
            raise HTTPException(
                409,
                "Test is published and cannot be modified. Duplicate it first.",
            )
        return test

    async def _persist_questions(
        self,
        test: Test,
        questions_data: list[dict[str, Any]],
        owner_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []

        # Get current max order
        result = await self.db.execute(
            select(func.coalesce(func.max(TestQuestion.order), 0)).where(
                TestQuestion.test_id == test.id
            )
        )
        current_order = result.scalar() or 0

        for q_data in questions_data:
            qtype_str = q_data.get("type", "multiple_choice")
            difficulty_str = q_data.get("difficulty", "medium")

            qtype_enum = _AI_TO_DB_QTYPE.get(qtype_str, QuestionType.SINGLE_CHOICE)
            diff_enum = _AI_TO_DB_DIFFICULTY.get(difficulty_str, DifficultyLevel.MEDIUM)

            correct_answers = q_data.get("correct_answers") or []
            correct_answer_str = correct_answers[0] if correct_answers else None

            qb_question = QBQuestion(
                title=q_data.get("title", ""),
                description=q_data.get("description") or None,
                question_type=qtype_enum,
                difficulty=diff_enum,
                score=q_data.get("points", 1),
                explanation=q_data.get("explanation", ""),
                correct_answer=correct_answer_str,
                visibility="private",
                status="draft",
                owner_id=owner_id,
            )
            self.db.add(qb_question)
            await self.db.flush()

            # Add choices
            options = q_data.get("options") or []
            for opt_idx, opt in enumerate(options):
                choice = Choice(
                    question_id=qb_question.id,
                    content=opt.get("text", ""),
                    is_correct=opt.get("is_correct", False),
                    order=opt_idx + 1,
                )
                self.db.add(choice)

            # Link to test
            current_order += 1
            tq = TestQuestion(
                test_id=test.id,
                question_id=qb_question.id,
                order=current_order,
                points=q_data.get("points", 1),
                required=True,
            )
            self.db.add(tq)
            await self.db.flush()

            created.append(
                {
                    "id": str(qb_question.id),
                    "title": qb_question.title,
                    "type": qtype_str,
                    "difficulty": difficulty_str,
                    "options": [
                        {"text": o.get("text", ""), "is_correct": o.get("is_correct", False)}
                        for o in options
                    ],
                    "correct_answers": correct_answers,
                    "explanation": qb_question.explanation,
                    "points": qb_question.score,
                }
            )

        await self.db.flush()
        return created
