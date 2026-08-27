"""Agent 1: read-only capability analysis."""

from __future__ import annotations

import json
from typing import Any

from .base import StructuredAgent
from ..config import LoadedProject
from ..models import CapabilityReport


class CapabilityAnalyzer(StructuredAgent[CapabilityReport]):
    prompt_name = "agent1.md"
    output_type = CapabilityReport

    def analyze(
        self,
        project: LoadedProject,
        *,
        feedback: dict[str, Any] | None = None,
    ) -> CapabilityReport:
        payload = {
            "project": project.manifest.model_dump(mode="json"),
            "resolved_repository": str(project.repository),
            "resolved_working_directory": str(project.working_directory),
            "capability_spec": project.capabilities.model_dump(mode="json"),
            "protocol_brief": project.protocol_brief,
            "feedback": feedback,
        }
        report = self._complete(json.dumps(payload, indent=2, sort_keys=True))
        if report.target != project.manifest.name:
            raise ValueError(
                f"capability report target {report.target!r} does not match "
                f"project {project.manifest.name!r}"
            )
        return report
