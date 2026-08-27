"""Agent 3: independent read-only semantic review."""

from __future__ import annotations

import json
from pathlib import Path

from .base import StructuredAgent
from ..config import LoadedProject
from ..models import CapabilityReport, InterfaceReport, ReviewReport


class IndependentReviewer(StructuredAgent[ReviewReport]):
    prompt_name = "agent3.md"
    output_type = ReviewReport

    def review(
        self,
        project: LoadedProject,
        capability_report: CapabilityReport,
        interface_report: InterfaceReport,
        worktree: Path,
        git_diff: str,
    ) -> ReviewReport:
        payload = {
            "original_repository": str(project.repository),
            "patched_worktree": str(worktree),
            "project": project.manifest.model_dump(mode="json"),
            "capability_spec": project.capabilities.model_dump(mode="json"),
            "capability_report": capability_report.model_dump(mode="json"),
            "interface_report": interface_report.model_dump(mode="json", exclude_none=True),
            "git_diff": git_diff,
        }
        return self._complete(json.dumps(payload, indent=2, sort_keys=True))
