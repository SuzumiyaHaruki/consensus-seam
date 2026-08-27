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
        feedback: dict[str, Any] | None = None,
    ) -> InterfaceReport:
        patchable = capability_report.patchable()
        if not patchable:
            raise ValueError("Transformer cannot run without PATCHABLE capabilities")
        payload = {
            "project": project.manifest.model_dump(mode="json"),
            "worktree": str(worktree),
            "patchable_capabilities": sorted(patchable),
            "capability_report": capability_report.model_dump(mode="json"),
            "capability_spec": project.capabilities.model_dump(mode="json"),
            "modification_policy": project.modification_policy.model_dump(mode="json"),
            "feedback": feedback,
        }
        result = self._complete(
            json.dumps(payload, indent=2, sort_keys=True),
            tools=transformer_tools(worktree, self.backend),
        )
        reported = set(result.capabilities())
        if reported != patchable:
            raise ValueError(
                "interface report must cover exactly the PATCHABLE capabilities; "
                f"expected {sorted(patchable)}, got {sorted(reported)}"
            )
        return result
