"""Minimal DeepSeek Chat Completions transport with no SDK dependency."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import AgentModelConfig
from .base import AgentRuntimeError


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 120,
    ) -> None:
        if not api_key:
            raise ValueError("DeepSeek API key cannot be empty")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def create_chat_completion(
        self,
        *,
        model: AgentModelConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, str] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model.model,
            "messages": messages,
            "stream": False,
            "thinking": {"type": model.thinking},
            "reasoning_effort": model.reasoning_effort,
            "max_tokens": model.max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if response_format is not None:
            body["response_format"] = response_format

        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:4000]
            raise AgentRuntimeError(f"DeepSeek API HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AgentRuntimeError(f"DeepSeek API request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise AgentRuntimeError("DeepSeek API returned a non-object response")
        return payload
