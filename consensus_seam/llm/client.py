"""Deterministic and placeholder LLM clients for the initial framework."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from .base import LLMClientError


class FakeLLMClient:
    """Consume predetermined responses in order for tests and local demos."""

    def __init__(self, responses: Iterable[str]) -> None:
        self._responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def from_json_file(cls, path: str | Path) -> "FakeLLMClient":
        with Path(path).open("r", encoding="utf-8") as handle:
            values = json.load(handle)
        if not isinstance(values, list):
            raise ValueError("response fixture must be a JSON array")
        responses = [value if isinstance(value, str) else json.dumps(value) for value in values]
        return cls(responses)

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_schema": response_schema,
            }
        )
        if not self._responses:
            raise LLMClientError("FakeLLMClient has no response remaining")
        return self._responses.popleft()


class UnconfiguredLLMClient:
    """Fail clearly until a real provider adapter is deliberately selected."""

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        raise LLMClientError(
            "no LLM adapter configured; pass --responses for deterministic framework runs"
        )
