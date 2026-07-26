"""AI question generation — prompt building and API calling."""

import json

import httpx

from app.core.config import settings


def build_ai_prompt(
    topic: str,
    count: int = 5,
    question_types: list[str] | None = None,
    language: str = "en",
) -> str:
    types = question_types or ["single_choice", "short_answer", "image"]
    types_str = ", ".join(types)
    return (
        f"Generate {count} quiz questions about '{topic}' in {language}.\n"
        f"Question types: {types_str}.\n"
        "Return ONLY valid JSON array (no markdown, no extra text).\n"
        "Each object must have:\n"
        "  - text (string, required)\n"
        "  - question_type (string: single_choice / short_answer / image)\n"
        "  - points (integer, default 1)\n"
        "  - correct_answer (string, for short_answer)\n"
        "  - explanation (string, optional)\n"
        "  - options (array of {text: string, is_correct: boolean}) — "
        "required for single_choice / image\n"
        "Example:\n"
        '[{"text": "What is 2+2?", "question_type": "single_choice", '
        '"points": 1, "options": [{"text": "3", "is_correct": false}, '
        '{"text": "4", "is_correct": true}]}]\n'
        f"Ensure exactly {count} questions, all valid JSON."
    )


def build_improve_prompt(question_text: str, language: str = "en") -> str:
    return (
        f"Improve this quiz question for clarity and educational value:\n\n"
        f'"{question_text}"\n\n'
        f"Return ONLY valid JSON object with:\n"
        f'  - improved_text (string)\n'
        f'  - explanation (string, why it was improved)\n'
        f"Language: {language}"
    )


def build_translate_prompt(text: str, target_language: str) -> str:
    return (
        f"Translate this quiz question to {target_language}:\n\n"
        f'"{text}"\n\n'
        f"Return ONLY valid JSON object with:\n"
        f'  - translated_text (string)\n'
        f'  - source_language (string)\n'
        f'  - target_language (string)\n'
        f"Preserve the educational meaning and question type."
    )


def build_explain_prompt(question_text: str, correct_answer: str, language: str = "en") -> str:
    return (
        f"Explain why the correct answer is '{correct_answer}' for this question:\n\n"
        f'"{question_text}"\n\n'
        f"Return ONLY valid JSON object with:\n"
        f'  - explanation (string, detailed explanation)\n'
        f'  - key_concepts (list of strings, main concepts covered)\n'
        f'  - difficulty_note (string, why this is the correct answer)\n'
        f"Language: {language}"
    )


def fallback_questions() -> list[dict]:
    return [
        {
            "text": "Sample: What is the capital of France?",
            "question_type": "single_choice",
            "points": 1,
            "options": [
                {"text": "London", "is_correct": False},
                {"text": "Paris", "is_correct": True},
                {"text": "Berlin", "is_correct": False},
                {"text": "Madrid", "is_correct": False},
            ],
            "explanation": "Paris is the capital of France.",
        },
    ]


async def call_ai_api(prompt: str) -> list[dict] | dict:
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        return fallback_questions()

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned)


async def improve_question(question_text: str, language: str = "en") -> dict:
    prompt = build_improve_prompt(question_text, language)
    result = await call_ai_api(prompt)
    if isinstance(result, list):
        if result:
            return result[0]
        return {
            "improved_text": question_text,
            "explanation": "No improvement suggested",
        }
    return result


async def translate_question(text: str, target_language: str) -> dict:
    prompt = build_translate_prompt(text, target_language)
    result = await call_ai_api(prompt)
    if isinstance(result, list):
        if result:
            return result[0]
        return {
            "translated_text": text,
            "source_language": "unknown",
            "target_language": target_language,
        }
    return result


async def explain_answer(question_text: str, correct_answer: str, language: str = "en") -> dict:
    prompt = build_explain_prompt(question_text, correct_answer, language)
    result = await call_ai_api(prompt)
    if isinstance(result, list):
        if result:
            return result[0]
        return {
            "explanation": "No explanation available",
            "key_concepts": [],
            "difficulty_note": "",
        }
    return result
