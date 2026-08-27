"""Strict structured-response support shared by the three Agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ..llm.base import AgentRuntime, ToolExecutor
from ..models import AgentModelConfig
from ..resources import resource_root


OutputT = TypeVar("OutputT", bound=BaseModel)


class AgentOutputError(ValueError):
    """Raised after all structured-output attempts fail validation."""


class StructuredAgent(Generic[OutputT]):
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
        return (self.prompt_directory / self.prompt_name).read_text(encoding="utf-8")

    def _complete(self, user_prompt: str, *, tools: ToolExecutor | None = None) -> OutputT:
        validation_error = ""
        for attempt in range(1, self.max_attempts + 1):
            retry_prompt = user_prompt
            if validation_error:
                retry_prompt += (
                    "\n\nYour previous response was rejected. Return corrected JSON only. "
                    f"Validation error:\n{validation_error}"
                )
            raw = self.runtime.run(
                self._system_prompt(),
                retry_prompt,
                self.output_type.model_json_schema(),
                model=self.model,
                tools=tools,
            )
            try:
                payload = json.loads(raw)
                return self.output_type.model_validate(payload)
            except (json.JSONDecodeError, ValidationError) as exc:
                validation_error = str(exc)
        raise AgentOutputError(
            f"{self.__class__.__name__} returned invalid output after "
            f"{self.max_attempts} attempts: {validation_error}"
        )
