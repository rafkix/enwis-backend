from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.modules.ai.providers.base import AIProvider

logger = logging.getLogger(__name__)

_GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiProvider(AIProvider):
    """Google Gemini (Generative Language API) provider."""

    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._api_key = api_key
        self._model = model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> list[dict[str, Any]]:
        url = _GEMINI_ENDPOINT.format(model=self._model)
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                params={"key": self._api_key},
                json=payload,
            )
            resp.raise_for_status()

        data = resp.json()
        text = self._extract_text(data)
        return self._parse_json(text)

    async def health_check(self) -> bool:
        if not self._api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    _GEMINI_ENDPOINT.format(model=self._model),
                    params={"key": self._api_key},
                )
                return resp.status_code in (200, 400, 405)
        except httpx.HTTPError:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini returned no candidates")
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise ValueError("Gemini returned empty content parts")
        return parts[0].get("text", "")

    @staticmethod
    def _parse_json(text: str) -> list[dict[str, Any]]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            parsed = parsed.get("questions", [parsed])
        if not isinstance(parsed, list):
            raise ValueError("Expected a JSON array of questions")
        return parsed
