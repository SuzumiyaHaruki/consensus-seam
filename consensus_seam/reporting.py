"""Creation and writing of deterministic run artifacts."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .models import CapabilityReport, CapabilityStatus


class ArtifactStore:
    """一次运行的结构化产物目录。"""

    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory.resolve()
        self.run_directory.mkdir(parents=True, exist_ok=False)
        (self.run_directory / "logs").mkdir()

    @classmethod
    def create(cls, runs_root: Path) -> "ArtifactStore":
        """使用 UTC 微秒时间戳创建不冲突的 run 目录。"""

        runs_root.mkdir(parents=True, exist_ok=True)
        stem = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        candidate = runs_root / stem
        suffix = 1
        while candidate.exists():
            candidate = runs_root / f"{stem}-{suffix}"
            suffix += 1
        return cls(candidate)

    def _path(self, name: str) -> Path:
        # 所有写入都经过此处，防止调用者用 ../ 把报告写出 run 目录。
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

    def write_unresolved(
        self,
        report: CapabilityReport,
        *,
        transform_capabilities: list[str] | None = None,
    ) -> Path:
        """汇总仍需人工处理或被实验范围主动跳过的能力。"""

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
            elif (
                finding.status is CapabilityStatus.PATCHABLE
                and transform_capabilities is not None
                and name not in transform_capabilities
            ):
                unresolved[name] = {
                    "status": finding.status.value,
                    "reason": "outside this run's transform_capabilities scope",
                }
        return self.write_json("unresolved.json", unresolved)

    def publish_latest(self) -> Path:
        """原子替换 Git 跟踪的 latest 审计导出。

        patched-worktree 可能包含完整目标仓库和未审核代码，既体积大又不适合
        上传；latest 只复制报告、最终 patch、统计和日志。先写 staging 再
        os.replace，避免复制到一半留下表面完整的目录。
        """

        runs_root = self.run_directory.parent
        latest = runs_root / "latest"
        staging = Path(tempfile.mkdtemp(prefix=".latest-", dir=runs_root))
        try:
            for source in self.run_directory.rglob("*"):
                relative = source.relative_to(self.run_directory)
                if any(part.startswith("patched-worktree") for part in relative.parts):
                    continue
                if not source.is_file():
                    continue
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

            manifest = {
                "source_run": self.run_directory.name,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "included": "reports, patch, statistics, and logs",
                "excluded": ["patched-worktree*"],
            }
            run_config_path = staging / "run-config.json"
            if run_config_path.is_file():
                run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
                manifest["experiment"] = run_config.get("experiment")
            (staging / "audit-manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (staging / "APPLY.md").write_text(
                """# Applying the latest verified patch

Review `changes.patch`, `review-report.json`, and `verification-report.json`
before modifying the target repository. Confirm the expected target revision in
`run-config.json`, then run from the target repository:

```bash
git apply --check /absolute/path/to/runs/latest/changes.patch
git apply /absolute/path/to/runs/latest/changes.patch
go test ./...
```

ConsensusSeam deliberately does not apply or commit the patch automatically.
""",
                encoding="utf-8",
            )
            if latest.exists():
                shutil.rmtree(latest)
            os.replace(staging, latest)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return latest
