"""Deterministic and placeholder LLM clients for the initial framework."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from ..models import AgentModelConfig
from .base import AgentRuntimeError, ToolExecutor


class FakeLLMClient:
    """A deterministic AgentRuntime for tests and response fixtures."""

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

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
        *,
        model: AgentModelConfig,
        tools: ToolExecutor | None = None,
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_schema": response_schema,
                "model": model.model_dump(mode="json"),
                "tools": [] if tools is None else tools.definitions,
            }
        )
        if not self._responses:
            raise AgentRuntimeError("FakeLLMClient has no response remaining")
        return self._responses.popleft()

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        """Compatibility shim for code written against the v0.1 text client."""

        return self.run(
            system_prompt,
            user_prompt,
            response_schema,
            model=AgentModelConfig(model="fake"),
        )


class UnconfiguredLLMClient:
    """Fail clearly until a real provider adapter is deliberately selected."""

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
        *,
        model: AgentModelConfig,
        tools: ToolExecutor | None = None,
    ) -> str:
        raise AgentRuntimeError(
            "no Agent runtime configured; pass --responses or set DEEPSEEK_API_KEY"
        )
