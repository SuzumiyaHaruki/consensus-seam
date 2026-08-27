"""The deliberately small LLM boundary used by Agents."""

from __future__ import annotations

from typing import Any, Protocol

from ..models import AgentModelConfig


class ToolExecutor(Protocol):
    @property
    def definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible function tool definitions."""

    def execute(self, name: str, raw_arguments: str) -> str:
        """Validate and execute one tool call, returning JSON text."""


class AgentRuntime(Protocol):
    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
        *,
        agent: str,
        model: AgentModelConfig,
        tools: ToolExecutor | None = None,
        invocation_id: str | None = None,
    ) -> str:
        """Run a bounded Agent turn, including local tool calls."""


class ChatCompletionClient(Protocol):
    def create_chat_completion(
        self,
        *,
        model: AgentModelConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, str] | None,
    ) -> dict[str, Any]:
        """Return one OpenAI-compatible chat completion response."""


class AgentRuntimeError(RuntimeError):
    """Raised when the configured LLM adapter cannot return a response."""


# Backward-compatible name for callers that imported the old exception.
LLMClientError = AgentRuntimeError
