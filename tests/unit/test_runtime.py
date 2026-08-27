from __future__ import annotations

import json
from typing import Any

from consensus_seam.llm.runtime import ToolCallingAgentRuntime
from consensus_seam.models import AgentModelConfig


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
            return {
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "prompt_cache_hit_tokens": 4,
                    "prompt_cache_miss_tokens": 6,
                },
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "I should inspect the source.",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "echo",
                                        "arguments": '{"value":"source"}',
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        return {
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 3,
                "total_tokens": 23,
                "prompt_cache_hit_tokens": 5,
                "prompt_cache_miss_tokens": 15,
            },
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '{"answer":"done"}',
                        "reasoning_content": "The evidence is sufficient.",
                    },
                }
            ]
        }


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
    assert stats[0]["model"] == "deepseek-v4-flash"
    assert stats[0]["api_calls"] == 2
    assert stats[0]["tool_calls"] == 1
    assert stats[0]["input_tokens"] == 30
    assert stats[0]["output_tokens"] == 5
    assert stats[0]["total_tokens"] == 35
    assert stats[0]["cache_hit_input_tokens"] == 9
    assert stats[0]["cache_miss_input_tokens"] == 21
    assert "reasoning_content" not in stats[0]
