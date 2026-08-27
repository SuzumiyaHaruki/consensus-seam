"""Creation and writing of deterministic run artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .models import CapabilityReport, CapabilityStatus


class ArtifactStore:
    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory.resolve()
        self.run_directory.mkdir(parents=True, exist_ok=False)
        (self.run_directory / "logs").mkdir()

    @classmethod
    def create(cls, runs_root: Path) -> "ArtifactStore":
        runs_root.mkdir(parents=True, exist_ok=True)
        stem = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        candidate = runs_root / stem
        suffix = 1
        while candidate.exists():
            candidate = runs_root / f"{stem}-{suffix}"
            suffix += 1
        return cls(candidate)

    def _path(self, name: str) -> Path:
        path = (self.run_directory / name).resolve()
        try:
            path.relative_to(self.run_directory)
        except ValueError as exc:
            raise ValueError("artifact path must stay inside run directory") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_model(self, name: str, model: BaseModel) -> Path:
        return self.write_text(name, model.model_dump_json(indent=2) + "\n")

    def write_json(self, name: str, value: Any) -> Path:
        return self.write_text(name, json.dumps(value, indent=2, sort_keys=True) + "\n")

    def write_text(self, name: str, value: str) -> Path:
        path = self._path(name)
        path.write_text(value, encoding="utf-8")
        return path

    def write_unresolved(self, report: CapabilityReport) -> Path:
        unresolved = {}
        for name, finding in report.capabilities.items():
            if finding.status in {
                CapabilityStatus.PARTIAL,
                CapabilityStatus.INVASIVE,
                CapabilityStatus.UNKNOWN,
            }:
                unresolved[name] = {
                    "status": finding.status.value,
                    "reason": finding.reason or finding.gap or "See capability-report.json",
                }
        return self.write_json("unresolved.json", unresolved)
