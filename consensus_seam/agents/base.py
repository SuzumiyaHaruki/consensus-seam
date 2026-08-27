"""Strict structured-response support shared by the three Agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ..llm.base import AgentRuntime, ToolExecutor
from ..models import AgentModelConfig
from ..resources import resource_root


OutputT = TypeVar("OutputT", bound=BaseModel)


class AgentOutputError(ValueError):
    """所有结构化输出尝试均无法通过校验时抛出。"""


class StructuredAgent(Generic[OutputT]):
    """三个 Agent 共用的 JSON Schema 输出与重试框架。

    Runtime 只负责得到模型文本；本类负责 JSON 解析、Pydantic 校验和角色
    特有的 post-validation，防止“差不多正确”的输出进入工作流。
    """

    agent_name: str
    prompt_name: str
    output_type: type[OutputT]

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        model: AgentModelConfig,
        prompt_directory: Path | None = None,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.runtime = runtime
        self.model = model
        self.prompt_directory = prompt_directory or resource_root() / "prompts"
        self.max_attempts = max_attempts

    def _system_prompt(self) -> str:
        """从受版本控制的 prompt 文件读取角色系统提示。"""

        return (self.prompt_directory / self.prompt_name).read_text(encoding="utf-8")

    def _complete(
        self,
        user_prompt: str,
        *,
        tools: ToolExecutor | None = None,
        post_validate: Callable[[OutputT], None] | None = None,
        invocation_id: str | None = None,
    ) -> OutputT:
        """执行最多 max_attempts 次结构化输出尝试。

        每次尝试拥有独立 invocation_id，便于关联具体 round 的 token 和工具
        成本。失败只反馈标准化校验错误，不会向 Agent 暴露隐藏 oracle。
        """

        validation_error = ""
        invocation_prefix = invocation_id or self.agent_name
        for attempt in range(1, self.max_attempts + 1):
            retry_prompt = user_prompt
            if validation_error:
                # 保留完整原始任务，只追加上一次结构错误，避免重试时丢失上下文。
                retry_prompt += (
                    "\n\nYour previous response was rejected. Return corrected JSON only. "
                    f"Validation error:\n{validation_error}"
                )
            raw = self.runtime.run(
                self._system_prompt(),
                retry_prompt,
                self.output_type.model_json_schema(),
                agent=self.agent_name,
                model=self.model,
                tools=tools,
                invocation_id=f"{invocation_prefix}-attempt{attempt}",
            )
            try:
                payload = json.loads(raw)
                result = self.output_type.model_validate(payload)
                if post_validate is not None:
                    post_validate(result)
                return result
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                validation_error = str(exc)
        raise AgentOutputError(
            f"{self.__class__.__name__} returned invalid output after "
            f"{self.max_attempts} attempts: {validation_error}"
        )
