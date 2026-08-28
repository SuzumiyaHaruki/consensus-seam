from __future__ import annotations

import json
from typing import Any

from consensus_seam.llm.runtime import ToolCallingAgentRuntime
from consensus_seam.models import AgentModelConfig


def completion(
    content: str | None,
    *,
    finish_reason: str = "stop",
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    return {
        "usage": usage or {},
        "choices": [{"finish_reason": finish_reason, "message": message}],
    }


def echo_call(call_id: str, value: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "echo", "arguments": json.dumps({"value": value})},
    }


class EchoTools:
    definitions = [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "echo a value",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    def execute(self, name: str, raw_arguments: str) -> str:
        assert name == "echo"
        return json.dumps({"ok": True, "result": json.loads(raw_arguments)["value"]})


class ScriptedChatClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return completion(
                None,
                finish_reason="tool_calls",
                tool_calls=[echo_call("call-1", "source")],
                reasoning_content="I should inspect the source.",
                usage={
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "prompt_cache_hit_tokens": 4,
                    "prompt_cache_miss_tokens": 6,
                },
            )
        return completion(
            '{"answer":"done"}',
            reasoning_content="The evidence is sufficient.",
            usage={
                "prompt_tokens": 20,
                "completion_tokens": 3,
                "total_tokens": 23,
                "prompt_cache_hit_tokens": 5,
                "prompt_cache_miss_tokens": 15,
            },
        )


class BudgetConvergenceClient:
    """工具可用时持续探索，最终无工具回合才返回结构化结果。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if kwargs["tools"] is not None:
            return completion(
                None,
                finish_reason="tool_calls",
                tool_calls=[echo_call(f"call-{len(self.calls)}", "more")],
            )
        return completion('{"answer":"converged"}')


def test_runtime_executes_tools_and_preserves_reasoning_content() -> None:
    client = ScriptedChatClient()
    runtime = ToolCallingAgentRuntime(client)
    result = runtime.run(
        "Return JSON.",
        "Inspect the repository.",
        {"type": "object"},
        agent="analyzer",
        model=AgentModelConfig(model="deepseek-v4-flash"),
        tools=EchoTools(),
        invocation_id="analyzer-a1-attempt1",
    )
    assert json.loads(result) == {"answer": "done"}
    second_messages = client.calls[1]["messages"]
    assert second_messages[2]["reasoning_content"] == "I should inspect the source."
    assert second_messages[3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"ok": true, "result": "source"}',
    }
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    stats = runtime.stats_snapshot()
    assert stats[0]["agent"] == "analyzer"
    assert stats[0]["invocation_id"] == "analyzer-a1-attempt1"
    assert stats[0]["model"] == "deepseek-v4-flash"
    assert stats[0]["api_calls"] == 2
    assert stats[0]["tool_calls"] == 1
    assert stats[0]["input_tokens"] == 30
    assert stats[0]["output_tokens"] == 5
    assert stats[0]["total_tokens"] == 35
    assert stats[0]["cache_hit_input_tokens"] == 9
    assert stats[0]["cache_miss_input_tokens"] == 21
    assert "reasoning_content" not in stats[0]
    audit = runtime.tool_audit_snapshot()
    assert len(audit) == 1
    assert audit[0]["agent"] == "analyzer"
    assert audit[0]["invocation_id"] == "analyzer-a1-attempt1"
    assert audit[0]["tool"] == "echo"
    assert audit[0]["arguments"] == {"value": "source"}
    assert audit[0]["output_bytes"] > 0
    assert audit[0]["success"] is True
    assert "result" not in audit[0]


def test_runtime_forces_final_json_before_tool_step_limit() -> None:
    client = BudgetConvergenceClient()
    runtime = ToolCallingAgentRuntime(client, max_steps=3)

    result = runtime.run(
        "Return JSON.",
        "Inspect and edit the repository.",
        {"type": "object"},
        agent="transformer",
        model=AgentModelConfig(model="deepseek-v4-flash"),
        tools=EchoTools(),
        invocation_id="transformer-message-control-attempt1",
    )

    assert json.loads(result) == {"answer": "converged"}
    assert len(client.calls) == 3
    assert client.calls[-1]["tools"] is None
    final_messages = client.calls[-1]["messages"]
    assert any(
        message.get("role") == "user"
        and "Tool use is now closed" in message.get("content", "")
        for message in final_messages
    )
    stats = runtime.stats_snapshot()
    assert stats[0]["status"] == "COMPLETED"
    assert stats[0]["api_calls"] == 3
    assert stats[0]["tool_calls"] == 2
