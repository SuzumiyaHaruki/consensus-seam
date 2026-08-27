"""Agent 3: independent read-only semantic review."""

from __future__ import annotations

import json
from pathlib import Path

from .base import StructuredAgent
from ..config import LoadedProject
from ..languages.go import GoBackend
from ..llm.base import AgentRuntime
from ..models import (
    AgentModelConfig,
    CapabilityReport,
    InterfaceReport,
    PatchMetrics,
    ReviewReport,
)
from ..tools import reviewer_tools


class IndependentReviewer(StructuredAgent[ReviewReport]):
    agent_name = "reviewer"
    prompt_name = "agent3.md"
    output_type = ReviewReport

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        model: AgentModelConfig,
        backend: GoBackend,
    ) -> None:
        super().__init__(runtime, model=model)
        self.backend = backend

    def review(
        self,
        project: LoadedProject,
        capability_report: CapabilityReport,
        interface_report: InterfaceReport,
        worktree: Path,
        git_diff: str,
        patch_metrics: PatchMetrics,
    ) -> ReviewReport:
        payload = {
            "original_repository": str(project.repository),
            "patched_worktree": str(worktree),
            "project": project.agent_manifest(),
            "capability_spec": project.capabilities.model_dump(mode="json"),
            "capability_report": capability_report.model_dump(mode="json"),
            "interface_report": interface_report.model_dump(mode="json", exclude_none=True),
            "git_diff": git_diff,
            "patch_metrics": patch_metrics.model_dump(mode="json"),
            "required_checks": sorted(ReviewReport.required_checks),
        }
        return self._complete(
            json.dumps(payload, indent=2, sort_keys=True),
            tools=reviewer_tools(project.repository, worktree, self.backend),
            post_validate=lambda report: report.validate_for_interface(interface_report),
        )
