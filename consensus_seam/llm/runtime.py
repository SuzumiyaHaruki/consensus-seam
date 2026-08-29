"""三个 Agent 角色共用的有界 Chat Completions 工具循环。"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from ..models import AgentModelConfig
from .base import AgentRuntimeError, ChatCompletionClient, ToolExecutor


@dataclass(frozen=True)
class AgentRunStats:
    """一次结构化 attempt 的聚合成本与状态，不含推理正文。"""

    agent: str
    invocation_id: str
    model: str
    status: str
    api_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_hit_input_tokens: int
    cache_miss_input_tokens: int
    api_wall_clock_seconds: float
    wall_clock_seconds: float
    error_type: str | None = None


@dataclass(frozen=True)
class ToolCallAudit:
    """一次工具调用的元数据；不保存返回源码或 patch 内容。"""

    agent: str
    invocation_id: str
    model: str
    tool: str
    arguments: dict[str, Any]
    output_bytes: int
    returned_lines: int | None
    duration_ms: float
    success: bool | None


class ToolCallingAgentRuntime:
    """执行 Chat Completions → tool calls → final JSON 的有界循环。"""

    def __init__(self, client: ChatCompletionClient, *, max_steps: int = 64) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.client = client
        self.max_steps = max_steps
        self._stats: list[AgentRunStats] = []
        self._tool_audit: list[ToolCallAudit] = []

    def stats_snapshot(self) -> list[dict[str, Any]]:
        """返回可序列化副本，调用者不能修改 Runtime 内部记录。"""

        return [asdict(item) for item in self._stats]

    def tool_audit_snapshot(self) -> list[dict[str, Any]]:
        """返回工具审计快照。"""

        return [asdict(item) for item in self._tool_audit]

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
        """运行一个 Agent attempt，直到得到最终文本或达到 max_steps。"""

        invocation_id = invocation_id or f"{agent}-unscoped"
        started = time.monotonic()
        api_calls = 0
        tool_call_count = 0
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        cache_hit_tokens = 0
        cache_miss_tokens = 0
        api_wall_clock = 0.0
        status = "FAILED"
        error_type: str | None = None
        # JSON Schema 同时通过系统提示和 response_format 约束模型；真正的
        # 可信校验仍在 StructuredAgent/Pydantic 中完成。
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

        try:
            reminder_step = self.max_steps - 8 if self.max_steps > 8 else None
            for step in range(self.max_steps):
                finalization_step = tools is not None and step == self.max_steps - 1
                if reminder_step is not None and step == reminder_step:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "The bounded tool budget is nearly exhausted. Stop "
                                "expanding scope. Finish only essential validation, "
                                "then return the required final JSON from the evidence "
                                "and worktree state already available."
                            ),
                        }
                    )
                if finalization_step:
                    # 最后一次模型调用不再暴露工具，要求它根据已经完成的
                    # worktree 和工具结果形成结构化结论。旧行为允许最后一次
                    # 继续调用工具，随后立即抛出上限异常，导致可用候选和已
                    # 通过的测试一起丢失。
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Tool use is now closed. Do not request another tool. "
                                "Return the required final JSON now. Describe unfinished "
                                "low-intrusion paths as uncovered or rediscovered rather "
                                "than continuing source exploration."
                            ),
                        }
                    )
                api_started = time.monotonic()
                response = self.client.create_chat_completion(
                    model=model,
                    messages=messages,
                    tools=None if finalization_step else definitions,
                    response_format={"type": "json_object"} if response_schema else None,
                )
                api_wall_clock += time.monotonic() - api_started
                # transport 会把 HTTP 重试次数附加在私有字段中，因此这里的
                # api_calls 表示真实 HTTP 请求数，而非逻辑轮数。
                api_calls += int(response.pop("_consensus_seam_http_attempts", 1))
                usage = response.get("usage") or {}
                input_tokens += int(usage.get("prompt_tokens", 0) or 0)
                output_tokens += int(usage.get("completion_tokens", 0) or 0)
                total_tokens += int(usage.get("total_tokens", 0) or 0)
                cache_hit_tokens += int(usage.get("prompt_cache_hit_tokens", 0) or 0)
                cache_miss_tokens += int(usage.get("prompt_cache_miss_tokens", 0) or 0)
                try:
                    choice = response["choices"][0]
                    message = choice["message"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise AgentRuntimeError(
                        "DeepSeek response is missing choices[0].message"
                    ) from exc

                assistant_message = self._assistant_message(message)
                messages.append(assistant_message)
                tool_calls = message.get("tool_calls") or []
                tool_call_count += len(tool_calls)
                if tool_calls:
                    if finalization_step:
                        raise AgentRuntimeError(
                            "model requested a tool during the forced finalization step"
                        )
                    if tools is None:
                        raise AgentRuntimeError(
                            "model requested tools but this Agent has none"
                        )
                    for call in tool_calls:
                        try:
                            call_id = call["id"]
                            function = call["function"]
                            tool_started = time.monotonic()
                            result = tools.execute(
                                function["name"], function["arguments"]
                            )
                            # 审计只记录脱敏参数、长度、条目数与耗时。工具完整
                            # 结果仍回传给模型，但不会落入 tool-call-audit。
                            self._tool_audit.append(
                                ToolCallAudit(
                                    agent=agent,
                                    invocation_id=invocation_id,
                                    model=model.model,
                                    tool=function["name"],
                                    arguments=self._summarize_arguments(
                                        function["arguments"]
                                    ),
                                    output_bytes=len(result.encode("utf-8")),
                                    returned_lines=self._returned_lines(result),
                                    duration_ms=(time.monotonic() - tool_started) * 1000,
                                    success=self._tool_success(result),
                                )
                            )
                        except (KeyError, TypeError) as exc:
                            raise AgentRuntimeError(
                                "malformed tool call in model response"
                            ) from exc
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
                    raise AgentRuntimeError(
                        "model returned neither tool calls nor final content"
                    )
                status = "COMPLETED"
                return content

            raise AgentRuntimeError(f"Agent tool loop exceeded {self.max_steps} steps")
        except BaseException as exc:
            api_calls += int(getattr(exc, "http_attempts", 0) or 0)
            error_type = type(exc).__name__
            raise
        finally:
            # 无论成功还是异常都记录 attempt，确保失败成本不会从实验统计中
            # 消失。error_type 只记录异常类名，不记录可能含敏感内容的消息。
            self._stats.append(
                AgentRunStats(
                    agent=agent,
                    invocation_id=invocation_id,
                    model=model.model,
                    status=status,
                    api_calls=api_calls,
                    tool_calls=tool_call_count,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cache_hit_input_tokens=cache_hit_tokens,
                    cache_miss_input_tokens=cache_miss_tokens,
                    api_wall_clock_seconds=api_wall_clock,
                    wall_clock_seconds=time.monotonic() - started,
                    error_type=error_type,
                )
            )

    @staticmethod
    def _summarize_arguments(raw_arguments: str) -> dict[str, Any]:
        """脱敏工具参数：源码/patch 只保留 UTF-8 字节数。"""

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {"invalid_json_bytes": len(raw_arguments.encode("utf-8"))}
        if not isinstance(arguments, dict):
            return {"argument_type": type(arguments).__name__}
        summary: dict[str, Any] = {}
        for key, value in arguments.items():
            if key in {"content", "patch"} and isinstance(value, str):
                summary[f"{key}_bytes"] = len(value.encode("utf-8"))
            elif isinstance(value, str):
                summary[key] = value[:200]
            elif isinstance(value, (int, float, bool)) or value is None:
                summary[key] = value
            elif isinstance(value, list):
                summary[f"{key}_items"] = len(value)
            elif isinstance(value, dict):
                summary[f"{key}_keys"] = sorted(value)[:20]
        return summary

    @staticmethod
    def _returned_lines(result: str) -> int | None:
        """从标准工具 JSON 中提取返回条目数，无法识别时返回 None。"""

        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        value = payload.get("result")
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            for key in ("lines", "matches", "files"):
                if isinstance(value.get(key), list):
                    return len(value[key])
        return None

    @staticmethod
    def _tool_success(result: str) -> bool | None:
        """读取工具标准响应的 ok 字段。"""

        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            return None
        return payload.get("ok") if isinstance(payload, dict) else None

    @staticmethod
    def _assistant_message(message: dict[str, Any]) -> dict[str, Any]:
        """保留下一轮 API 所需字段，避免保存无关响应元数据。"""

        preserved = {"role": "assistant", "content": message.get("content")}
        # DeepSeek thinking 模式要求工具调用后的下一请求原样带回
        # reasoning_content；它只存在于内存消息链，不写入统计产物。
        if "reasoning_content" in message:
            preserved["reasoning_content"] = message["reasoning_content"]
        if message.get("tool_calls"):
            preserved["tool_calls"] = message["tool_calls"]
        return preserved
