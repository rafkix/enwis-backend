from __future__ import annotations

from typing import Any

from app.modules.ai.exceptions import AIResponseValidationError
from app.modules.ai.schemas import (
    ALLOWED_DIFFICULTY_LEVELS,
    ALLOWED_QUESTION_TYPES,
)


def validate_ai_response(raw: list[dict[str, Any]], *, expected_count: int) -> list[dict[str, Any]]:
    """Validate and normalise raw AI output.

    Raises ``AIResponseValidationError`` for any structural or content
    issues.  Returns a cleaned list of question dicts ready for
    persistence.
    """
    if not raw:
        raise AIResponseValidationError("AI returned an empty response")

    validated: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    for idx, item in enumerate(raw, 1):
        _validate_single(item, idx, seen_titles)
        validated.append(item)

    if len(validated) > expected_count:
        validated = validated[:expected_count]

    if len(validated) < expected_count:
        raise AIResponseValidationError(
            f"Expected at least {expected_count} questions but got {len(validated)}"
        )

    return validated


def _validate_single(item: dict[str, Any], idx: int, seen_titles: set[str]) -> None:
    title = item.get("title") or item.get("text")
    if not title or not isinstance(title, str) or not title.strip():
        raise AIResponseValidationError(f"Question #{idx} is missing a title")

    title_normalized = title.strip().lower()
    if title_normalized in seen_titles:
        raise AIResponseValidationError(f"Question #{idx} is a duplicate: '{title.strip()}'")
    seen_titles.add(title_normalized)

    qtype = item.get("type") or item.get("question_type", "multiple_choice")
    if qtype not in ALLOWED_QUESTION_TYPES:
        raise AIResponseValidationError(
            f"Question #{idx} has invalid type '{qtype}'. "
            f"Allowed: {', '.join(ALLOWED_QUESTION_TYPES)}"
        )
    item["type"] = qtype

    difficulty = item.get("difficulty", "medium")
    if difficulty not in ALLOWED_DIFFICULTY_LEVELS:
        item["difficulty"] = "medium"

    if qtype in ("multiple_choice", "true_false", "multiple_select"):
        options = item.get("options") or []
        if not options:
            raise AIResponseValidationError(
                f"Question #{idx} ({qtype}) must have options"
            )
        if qtype == "true_false" and len(options) < 2:
            raise AIResponseValidationError(
                f"Question #{idx} (true_false) must have at least 2 options"
            )
        if qtype == "multiple_choice":
            correct = [o for o in options if o.get("is_correct")]
            if not correct:
                raise AIResponseValidationError(
                    f"Question #{idx} (multiple_choice) must have exactly one correct answer"
                )

    correct_answers = item.get("correct_answers") or []
    if qtype in ("multiple_choice", "true_false") and not correct_answers:
        options = item.get("options") or []
        correct_opts = [o["text"] for o in options if o.get("is_correct")]
        if correct_opts:
            item["correct_answers"] = correct_opts
        elif not correct_answers:
            raise AIResponseValidationError(
                f"Question #{idx} has no correct answer indicated"
            )

    if qtype in ("short_answer", "essay", "numeric") and not correct_answers:
        ca = item.get("correct_answer")
        if ca:
            item["correct_answers"] = [ca]

    points = item.get("points")
    if not isinstance(points, int) or points < 1:
        item["points"] = 1

    explanation = item.get("explanation", "")
    if not explanation or not isinstance(explanation, str) or not explanation.strip():
        item["explanation"] = f"Answer explanation for: {title.strip()}"
