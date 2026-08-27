"""Agent 2: low-intrusion changes in an isolated worktree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import StructuredAgent
from ..config import LoadedProject
from ..languages.go import GoBackend
from ..llm.base import AgentRuntime
from ..models import AgentModelConfig, CapabilityReport, InterfaceReport
from ..tools import transformer_tools


class LowIntrusionTransformer(StructuredAgent[InterfaceReport]):
    agent_name = "transformer"
    prompt_name = "agent2.md"
    output_type = InterfaceReport

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        model: AgentModelConfig,
        backend: GoBackend,
    ) -> None:
        super().__init__(runtime, model=model)
        self.backend = backend

    def transform(
        self,
        project: LoadedProject,
        capability_report: CapabilityReport,
        worktree: Path,
        *,
        selected_capabilities: set[str] | None = None,
        feedback: dict[str, Any] | None = None,
        invocation_id: str | None = None,
    ) -> InterfaceReport:
        patchable = capability_report.patchable(selected_capabilities)
        if not patchable:
            raise ValueError(
                "Transformer cannot run without selected PATCHABLE capabilities"
            )
        payload = {
            "project": project.agent_manifest(),
            "worktree": str(worktree),
            "patchable_capabilities": sorted(patchable),
            "transform_capabilities": (
                None
                if project.manifest.transform_capabilities is None
                else list(project.manifest.transform_capabilities)
            ),
            "capability_report": capability_report.model_dump(mode="json"),
            "capability_spec": project.capabilities.model_dump(mode="json"),
            "modification_policy": project.modification_policy.model_dump(mode="json"),
            "feedback": feedback,
        }
        result = self._complete(
            json.dumps(payload, indent=2, sort_keys=True),
            tools=transformer_tools(worktree, self.backend),
            invocation_id=invocation_id,
        )
        reported = set(result.capabilities())
        if reported != patchable:
            raise ValueError(
                "interface report must cover exactly the selected PATCHABLE capabilities; "
                f"expected {sorted(patchable)}, got {sorted(reported)}"
            )
        return result
