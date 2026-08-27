"""创建并写入确定性的实验产物。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .models import CapabilityReport, CapabilityStatus, CodeLocation, InterfaceReport


CAPABILITY_DISPLAY_ORDER = (
    ("message_capture", "消息捕获"),
    ("message_injection", "消息注入"),
    ("time_control", "时间控制"),
    ("randomness_control", "随机性控制"),
    ("lifecycle_control", "生命周期控制"),
    ("observation", "状态观察"),
    ("external_input", "外部输入"),
)


def _format_location(location: CodeLocation | None) -> str | None:
    """把 Agent 2 的代码位置转换成适合人读的短文本。"""

    if location is None:
        return None
    parts = [part for part in (location.file, location.symbol) if part]
    value = " / ".join(parts)
    return f"{value}：{location.meaning}" if location.meaning else value


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
                    "reason": finding.reason or finding.gap or "详见 capability-report.json",
                }
            elif (
                finding.status is CapabilityStatus.PATCHABLE
                and transform_capabilities is not None
                and name not in transform_capabilities
            ):
                unresolved[name] = {
                    "status": finding.status.value,
                    "reason": "不在本次 transform_capabilities 实验范围内",
                }
        return self.write_json("unresolved.json", unresolved)

    def write_usage(
        self,
        report: CapabilityReport,
        interface_report: InterfaceReport | None = None,
    ) -> Path:
        """用现有结构化报告生成面向使用者的中文接口说明。"""

        lines = [
            f"# {report.target} 测试接口使用报告",
            "",
            "本报告同时列出目标系统已有接口和本次 Agent 生成的接口。",
            "能力状态、源码证据和完整限制以 `capability-report.json` 为准。",
            "",
        ]
        implemented = interface_report.capabilities() if interface_report else {}
        for name, title in CAPABILITY_DISPLAY_ORDER:
            finding = report.capabilities[name]
            generated = implemented.get(name)
            lines.extend([f"## {title}", "", f"- 分析状态：`{finding.status.value}`"])
            if finding.boundary:
                lines.append(f"- 覆盖边界：{finding.boundary}")
            lines.append(
                "- 现有测试接口是否完整："
                + ("是" if finding.existing_test_interface_complete else "否")
            )
            if finding.test_support_reason:
                lines.append(f"- 测试支持判断：{finding.test_support_reason}")
            if generated is not None:
                lines.append(
                    "- 本次修改："
                    + ("已生成接口" if generated.implemented else "实现阶段判定为侵入式")
                )
            lines.append("")

            if finding.execution_paths:
                lines.extend(["### Analyzer 发现的实现路径", ""])
                lines.extend(f"- {path}" for path in finding.execution_paths)
                lines.append("")

            if finding.suggested_changes:
                lines.extend(["### 建议改造", ""])
                lines.extend(f"- {item}" for item in finding.suggested_changes)
                lines.append("")

            if finding.entrypoints:
                lines.extend(["### 目标已有入口", ""])
                lines.extend(f"- `{entrypoint}`" for entrypoint in finding.entrypoints)
                lines.append("")
            elif finding.evidence:
                # 某些旧报告没有 entrypoints；至少把可定位证据呈现出来，避免
                # SUPPORTED 能力在使用报告中完全消失。
                lines.extend(["### 可参考的源码位置", ""])
                for item in finding.evidence:
                    location = item.file or item.symbol or "未定位"
                    if item.line is not None:
                        location += f":{item.line}"
                    lines.append(f"- `{location}`：{item.reason}")
                lines.append("")

            if generated is not None and generated.implemented:
                locations = [
                    ("捕获位置", _format_location(generated.capture_boundary)),
                    ("Pending Store", _format_location(generated.pending_store)),
                    ("调用入口", _format_location(generated.entrypoint)),
                ]
                present = [(label, value) for label, value in locations if value]
                if present:
                    lines.extend(["### 本次生成接口", ""])
                    lines.extend(f"- {label}：`{value}`" for label, value in present)
                    lines.append("")
                details = [
                    ("生产路径", generated.production_mode),
                    ("测试路径", generated.test_mode),
                    ("消息 ID 范围", generated.message_id_scope),
                    ("复制策略", generated.copy_strategy),
                ]
                present_details = [(label, value) for label, value in details if value]
                if present_details or generated.notes:
                    lines.extend(["### 使用与范围", ""])
                    lines.extend(f"- {label}：{value}" for label, value in present_details)
                    lines.extend(f"- {note}" for note in generated.notes)
                    lines.append("")
                if generated.covered_paths:
                    lines.extend(["### 已覆盖路径", ""])
                    lines.extend(f"- {path}" for path in generated.covered_paths)
                    lines.append("")
                if generated.uncovered_paths:
                    lines.extend(["### 未覆盖路径", ""])
                    lines.extend(f"- {path}" for path in generated.uncovered_paths)
                    lines.append("")
                if generated.implementation_approach:
                    lines.extend(["### 实际实现方式", ""])
                    lines.extend(f"- {item}" for item in generated.implementation_approach)
                    lines.append("")

            if finding.limitations:
                lines.extend(["### 限制", ""])
                lines.extend(f"- {item}" for item in finding.limitations)
                lines.append("")
            elif finding.gap and (generated is None or not generated.implemented):
                lines.extend(["### 当前缺口", "", f"- {finding.gap}", ""])

        return self.write_text("USAGE.md", "\n".join(lines).rstrip() + "\n")

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
                "included": "报告、补丁、统计和日志",
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
                """# 应用最近一次已验证补丁

修改目标仓库前，先审查 `changes.patch`、`review-report.json` 和
`verification-report.json`，并在 `run-config.json` 中确认目标提交版本。

然后在目标仓库中运行：

```bash
git apply --check /绝对路径/runs/latest/changes.patch
git apply /绝对路径/runs/latest/changes.patch
go test ./...
```

ConsensusSeam 不会自动应用或提交补丁。

如果最近一次运行是 analyze-only，目录中可能没有 `changes.patch`；此时本文件只说明通用应用流程。
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
