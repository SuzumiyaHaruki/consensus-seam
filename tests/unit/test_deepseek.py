from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import consensus_seam.llm.deepseek as deepseek_module
from consensus_seam.llm.deepseek import DeepSeekClient
from consensus_seam.models import AgentModelConfig


class FakeHTTPResponse:
    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}'


def test_deepseek_client_uses_chat_completions_payload(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> FakeHTTPResponse:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeHTTPResponse()

    monkeypatch.setattr(deepseek_module, "urlopen", fake_urlopen)
    client = DeepSeekClient("secret", timeout_seconds=15)
    response = client.create_chat_completion(
        model=AgentModelConfig(
            model="deepseek-v4-flash",
            thinking="enabled",
            reasoning_effort="max",
            max_tokens=4096,
        ),
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
        response_format={"type": "json_object"},
    )
    assert response["choices"][0]["finish_reason"] == "stop"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["body"]["model"] == "deepseek-v4-flash"
    assert captured["body"]["thinking"] == {"type": "enabled"}
    assert captured["body"]["reasoning_effort"] == "max"
    assert captured["body"]["tool_choice"] == "auto"
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_deepseek_client_retries_429_with_bounded_backoff(monkeypatch: Any) -> None:
    attempts = 0
    delays: list[float] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeHTTPResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(
                request.full_url,
                429,
                "rate limited",
                {"Retry-After": "0.25"},
                BytesIO(b'{"error":"rate limited"}'),
            )
        return FakeHTTPResponse()

    monkeypatch.setattr(deepseek_module, "urlopen", fake_urlopen)
    client = DeepSeekClient("secret", sleep=delays.append)
    response = client.create_chat_completion(
        model=AgentModelConfig(model="deepseek-v4-flash"),
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        response_format=None,
    )
    assert response["_consensus_seam_http_attempts"] == 2
    assert attempts == 2
    assert delays == [0.25]
