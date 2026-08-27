"""初始框架使用的确定性与占位 LLM Client。"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from ..models import AgentModelConfig
from .base import AgentRuntimeError, ToolExecutor


class FakeLLMClient:
    """按队列返回固定响应的确定性开发 Runtime。

    它不产生网络请求或 token 成本，适合测试工作流状态机、结构化重试与
    CLI。calls 会记录传入 Prompt/Schema，供测试验证信息边界。
    """

    def __init__(self, responses: Iterable[str]) -> None:
        self._responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def from_json_file(cls, path: str | Path) -> "FakeLLMClient":
        """从 JSON 数组构造队列；对象元素会先序列化成 JSON 文本。"""

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
        agent: str,
        model: AgentModelConfig,
        tools: ToolExecutor | None = None,
        invocation_id: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_schema": response_schema,
                "agent": agent,
                "invocation_id": invocation_id,
                "model": model.model_dump(mode="json"),
                "tools": [] if tools is None else tools.definitions,
            }
        )
        if not self._responses:
            raise AgentRuntimeError("FakeLLMClient has no response remaining")
        return self._responses.popleft()


class UnconfiguredLLMClient:
    """未选择真实或 Fake Runtime 时提供明确错误。"""

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
        raise AgentRuntimeError(
            "no Agent runtime configured; pass --responses or set DEEPSEEK_API_KEY"
        )
