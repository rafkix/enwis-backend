from __future__ import annotations

import abc
from typing import Any


class AIProvider(abc.ABC):
    """Abstract interface for AI question-generation providers.

    Every concrete provider must implement ``generate`` which accepts a
    prompt string and returns a parsed JSON-serialisable response (typically
    a ``list[dict]`` of question objects).
    """

    name: str

    @abc.abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> list[dict[str, Any]]:
        """Send *prompt* to the provider and return parsed questions."""
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return ``True`` if the provider is reachable and configured."""
        ...
