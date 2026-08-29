"""Agent 使用的最小 LLM 边界。"""

from __future__ import annotations

from typing import Any, Protocol

from ..models import AgentModelConfig


class ToolExecutor(Protocol):
    """Runtime 所依赖的最小工具注册/执行协议。"""

    @property
    def definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible function tool definitions."""

    def execute(self, name: str, raw_arguments: str) -> str:
        """Validate and execute one tool call, returning JSON text."""


class AgentRuntime(Protocol):
    """Agent 与具体模型供应商之间的抽象边界。"""

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
    """OpenAI-compatible Chat Completions transport 的最小接口。"""

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
    """模型 transport 或工具循环无法返回有效响应时抛出。"""

    def __init__(self, message: str, *, http_attempts: int = 0) -> None:
        super().__init__(message)
        self.http_attempts = http_attempts


# 保留异常别名只影响 import 兼容性，不恢复已删除的旧文本客户端行为。
LLMClientError = AgentRuntimeError
