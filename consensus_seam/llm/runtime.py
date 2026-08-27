"""Bounded Chat Completions tool loop used by all three Agent roles."""

from __future__ import annotations

import json
from typing import Any

from ..models import AgentModelConfig
from .base import AgentRuntimeError, ChatCompletionClient, ToolExecutor


class ToolCallingAgentRuntime:
    def __init__(self, client: ChatCompletionClient, *, max_steps: int = 64) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.client = client
        self.max_steps = max_steps

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
        *,
        model: AgentModelConfig,
        tools: ToolExecutor | None = None,
    ) -> str:
        schema_instruction = ""
        if response_schema is not None:
            schema_instruction = (
                "\n\nYour final response must be a JSON object matching this JSON Schema. "
                "Do not wrap it in Markdown:\n"
                + json.dumps(response_schema, sort_keys=True)
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt + schema_instruction},
            {"role": "user", "content": user_prompt},
        ]
        definitions = None if tools is None else tools.definitions

        for _ in range(self.max_steps):
            response = self.client.create_chat_completion(
                model=model,
                messages=messages,
                tools=definitions,
                response_format={"type": "json_object"} if response_schema else None,
            )
            try:
                choice = response["choices"][0]
                message = choice["message"]
            except (KeyError, IndexError, TypeError) as exc:
                raise AgentRuntimeError("DeepSeek response is missing choices[0].message") from exc

            assistant_message = self._assistant_message(message)
            messages.append(assistant_message)
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                if tools is None:
                    raise AgentRuntimeError("model requested tools but this Agent has none")
                for call in tool_calls:
                    try:
                        call_id = call["id"]
                        function = call["function"]
                        result = tools.execute(function["name"], function["arguments"])
                    except (KeyError, TypeError) as exc:
                        raise AgentRuntimeError("malformed tool call in model response") from exc
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": result,
                        }
                    )
                continue

            finish_reason = choice.get("finish_reason")
            if finish_reason == "length":
                raise AgentRuntimeError("model output was truncated at max_tokens")
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise AgentRuntimeError("model returned neither tool calls nor final content")
            return content

        raise AgentRuntimeError(f"Agent tool loop exceeded {self.max_steps} steps")

    @staticmethod
    def _assistant_message(message: dict[str, Any]) -> dict[str, Any]:
        preserved = {"role": "assistant", "content": message.get("content")}
        # DeepSeek thinking-mode tool calls require reasoning_content to be passed
        # back exactly on the following request.
        if "reasoning_content" in message:
            preserved["reasoning_content"] = message["reasoning_content"]
        if message.get("tool_calls"):
            preserved["tool_calls"] = message["tool_calls"]
        return preserved
