"""Agent 1：只读能力分析。"""

from __future__ import annotations

import json
from typing import Any

from .base import StructuredAgent
from ..config import LoadedProject
from ..languages.go import GoBackend
from ..llm.base import AgentRuntime
from ..models import AgentModelConfig, CapabilityReport
from ..tools import analyzer_tools


class CapabilityAnalyzer(StructuredAgent[CapabilityReport]):
    """Agent 1：只读发现能力、边界、缺口和代码证据。"""

    agent_name = "analyzer"
    prompt_name = "agent1.md"
    output_type = CapabilityReport

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        model: AgentModelConfig,
        backend: GoBackend,
    ) -> None:
        super().__init__(runtime, model=model)
        self.backend = backend

    def analyze(
        self,
        project: LoadedProject,
        *,
        feedback: dict[str, Any] | None = None,
        invocation_id: str | None = None,
    ) -> CapabilityReport:
        # target 是机器关联键，不能扩展为“仓库名 + 说明”。放进 post-
        # validation 后，名称错误会触发 attempt2，而不是直接终止运行。
        def validate_target(report: CapabilityReport) -> None:
            if report.target != project.manifest.name:
                raise ValueError(
                    f"capability report target {report.target!r} does not match "
                    f"project {project.manifest.name!r}"
                )

        # agent_manifest 已剔除隐藏命令、fixture 和实验标签；Analyzer 只获得
        # 通用能力规范、协议简介和目标源码的只读工具。
        payload = {
            "project": project.agent_manifest(),
            "resolved_repository": str(project.repository),
            "resolved_working_directory": str(project.working_directory),
            "capability_spec": project.capabilities.model_dump(mode="json"),
            "protocol_brief": project.protocol_brief,
            "feedback": feedback,
        }
        report = self._complete(
            json.dumps(payload, indent=2, sort_keys=True),
            tools=analyzer_tools(project.repository, self.backend),
            post_validate=validate_target,
            invocation_id=invocation_id,
        )
        return report
