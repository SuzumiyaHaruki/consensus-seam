"""The deliberately small LLM boundary used by Agents."""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        """Return one raw response; callers perform strict validation."""


class LLMClientError(RuntimeError):
    """Raised when the configured LLM adapter cannot return a response."""
