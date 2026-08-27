"""Minimal DeepSeek Chat Completions transport with no SDK dependency."""

from __future__ import annotations

import json
import time
from typing import Any, Callable
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
        max_attempts: int = 3,
        retry_base_delay_seconds: float = 1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("DeepSeek API key cannot be empty")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds cannot be negative")
        self.max_attempts = max_attempts
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self._sleep = sleep

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

        for attempt in range(1, self.max_attempts + 1):
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
                if not isinstance(payload, dict):
                    raise AgentRuntimeError("DeepSeek API returned a non-object response")
                payload["_consensus_seam_http_attempts"] = attempt
                return payload
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:4000]
                retriable = exc.code == 429 or 500 <= exc.code < 600
                if not retriable or attempt == self.max_attempts:
                    raise AgentRuntimeError(
                        f"DeepSeek API HTTP {exc.code}: {detail}"
                    ) from exc
                headers = exc.headers or {}
                self._sleep(self._retry_delay(attempt, headers.get("Retry-After")))
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt == self.max_attempts:
                    raise AgentRuntimeError(f"DeepSeek API request failed: {exc}") from exc
                self._sleep(self._retry_delay(attempt))

        raise AgentRuntimeError("DeepSeek API retry loop ended unexpectedly")

    def _retry_delay(self, attempt: int, retry_after: str | None = None) -> float:
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0), 30)
            except ValueError:
                pass
        return min(self.retry_base_delay_seconds * (2 ** (attempt - 1)), 30)
