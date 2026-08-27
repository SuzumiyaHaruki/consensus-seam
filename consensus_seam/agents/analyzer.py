"""Agent 1: read-only capability analysis."""

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
    ) -> CapabilityReport:
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
        )
        if report.target != project.manifest.name:
            raise ValueError(
                f"capability report target {report.target!r} does not match "
                f"project {project.manifest.name!r}"
            )
        return report
