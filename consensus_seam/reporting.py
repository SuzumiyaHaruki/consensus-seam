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

from .models import (
    CapabilityReport,
    CapabilityStatus,
    CodeLocation,
    InterfaceReport,
    ReviewReport,
)


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


def _markdown_cell(values: list[str], *, limit: int = 3) -> str:
    """把接口列表压缩成不会破坏 Markdown 表格的单元格。"""

    cleaned = [value.replace("|", "\\|") for value in values if value]
    visible = cleaned[:limit]
    result = "<br>".join(f"`{value}`" for value in visible)
    if len(cleaned) > limit:
        suffix = f"等 {len(cleaned)} 项"
        result = f"{result}<br>{suffix}" if result else suffix
    return result or "—"


def _generated_locations(capability: object | None) -> list[str]:
    """提取 Agent 2 报告中测试方可调用的公开入口。"""

    if capability is None:
        return []
    values: list[str] = []
    locations = list(getattr(capability, "public_entrypoints", ()))
    if not locations:
        legacy = getattr(capability, "entrypoint", None)
        locations = [] if legacy is None else [legacy]
    for location in locations:
        if location is None:
            continue
        value = location.symbol or location.file
        if value and value not in values:
            values.append(value)
    return values


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

    def mark_incomplete(self, error_type: str) -> Path:
        """标记异常中断的 run，避免阶段性报告被误认为最终接口说明。"""

        marker = "本次运行未完成，以下内容仅反映中断前已经产生的阶段性结果。"
        warning = [
            "> [!WARNING]",
            f"> {marker}",
            "> 生成接口、调用示例和 Reviewer 结论可能缺失，不得作为最终使用说明。",
            "",
        ]
        for name in ("USAGE.md", "AUDIT.md"):
            path = self._path(name)
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            if marker in content:
                continue
            lines = content.splitlines()
            insert_at = 2 if lines and lines[0].startswith("# ") else 0
            lines[insert_at:insert_at] = warning
            path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return self.write_json(
            "failure.json",
            {"outcome": "INCOMPLETE", "error_type": error_type},
        )

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
        review_report: ReviewReport | None = None,
    ) -> Path:
        """生成面向测试方的简洁接口矩阵、调用入口和示例。"""

        # 详细分析单独保存，USAGE 不再承担完整审计报告的职责。
        self._write_audit(report, interface_report, review_report)
        generated = interface_report.capabilities() if interface_report else {}
        lines = [
            f"# {report.target} 测试接口清单",
            "",
            "本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。",
            "详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。",
            "",
            "## 快速接口矩阵",
            "",
            "| 能力 | 修改前状态 | 目标已有入口 | 本次生成入口 | 当前结论 |",
            "|---|---|---|---|---|",
        ]
        for name, title in CAPABILITY_DISPLAY_ORDER:
            finding = report.capabilities[name]
            capability = generated.get(name)
            existing = finding.entrypoints or [
                item.symbol or item.file or ""
                for item in finding.evidence
                if item.symbol or item.file
            ]
            new_entries = _generated_locations(capability)
            if capability is not None and capability.implemented:
                covered = len(capability.covered_paths)
                uncovered = len(capability.uncovered_paths)
                conclusion = "已生成接口"
                if covered or uncovered:
                    conclusion += f"；覆盖 {covered} 条路径"
                    if uncovered:
                        conclusion += f"，未覆盖 {uncovered} 条"
            elif finding.status is CapabilityStatus.SUPPORTED:
                conclusion = "直接复用目标已有接口"
            elif finding.status is CapabilityStatus.PATCHABLE:
                conclusion = "尚需低侵入补充"
            else:
                conclusion = finding.status.value
            lines.append(
                "| "
                + " | ".join(
                    (
                        title,
                        f"`{finding.status.value}`",
                        _markdown_cell(existing),
                        _markdown_cell(new_entries),
                        conclusion,
                    )
                )
                + " |"
            )

        message_capabilities = [
            generated.get("message_capture"),
            generated.get("message_injection"),
        ]
        if any(
            capability is not None and capability.implemented
            for capability in message_capabilities
        ):
            lines.extend(
                [
                    "",
                    "## 消息控制调用顺序",
                    "",
                    "1. 调用报告列出的 NewMessageController 构造器并完成目标接线。",
                    "2. 调用 Pending，获得可检查的消息深拷贝快照和稳定 Handle。",
                    "3. 测试代码根据目标原生消息字段选择实例；ConsensusSeam 不决定选择策略。",
                    "4. 将同一 Handle 交给 Drop 或 Inject；需要全部丢弃时调用 Clear。",
                    "5. 根据下方记录的接受点、错误类别和缓存变化决定后续测试动作。",
                ]
            )

        lines.extend(["", "## 接口详情与示例", ""])
        for name, title in CAPABILITY_DISPLAY_ORDER:
            finding = report.capabilities[name]
            capability = generated.get(name)
            lines.extend([f"### {title}", ""])
            if finding.entrypoints:
                lines.append("**目标已有入口**")
                lines.append("")
                lines.extend(f"- `{item}`" for item in finding.entrypoints)
                lines.append("")
            locations = _generated_locations(capability)
            if locations:
                lines.append("**本次生成入口**")
                lines.append("")
                lines.extend(f"- `{item}`" for item in locations)
                lines.append("")
            if capability is not None and capability.implemented:
                if capability.test_mode:
                    lines.extend(["**启用与使用范围**", "", capability.test_mode, ""])
                if capability.instance_reference:
                    lines.extend(
                        ["**缓存实例引用**", "", capability.instance_reference, ""]
                    )
                if capability.target_binding_strategy:
                    lines.extend(
                        [
                            "**目标绑定方式**",
                            "",
                            capability.target_binding_strategy,
                            "",
                        ]
                    )
                if capability.cache_effects:
                    lines.extend(
                        ["**缓存变化与失败语义**", "", capability.cache_effects, ""]
                    )
                if capability.uncovered_paths:
                    lines.append("**仍未覆盖**")
                    lines.append("")
                    lines.extend(f"- {item}" for item in capability.uncovered_paths)
                    lines.append("")
            examples = list(finding.usage_examples)
            if capability is not None:
                examples.extend(capability.usage_examples)
            if examples:
                lines.append("**调用示例**")
                lines.append("")
                for example in examples:
                    lines.extend(["```go", example.rstrip(), "```", ""])
            if not finding.entrypoints and not locations and not examples:
                reason = finding.test_support_reason or finding.reason or finding.gap
                lines.extend([reason or "本次没有可直接列出的调用入口。", ""])

        if review_report is not None:
            lines.extend(
                [
                    "## Reviewer 最终结论",
                    "",
                    f"- 总体结论：`{review_report.overall.value}`",
                ]
            )
            if review_report.issues:
                lines.append("- 阻塞问题：")
                lines.extend(f"  - {issue.reason}" for issue in review_report.issues)
            if review_report.risks:
                lines.append("- 非阻塞剩余风险：")
                lines.extend(f"  - {risk}" for risk in review_report.risks)
            if not review_report.issues and not review_report.risks:
                lines.append("- Reviewer 未报告阻塞问题或剩余风险。")
            lines.append("")

        return self.write_text("USAGE.md", "\n".join(lines).rstrip() + "\n")

    def _write_audit(
        self,
        report: CapabilityReport,
        interface_report: InterfaceReport | None = None,
        review_report: ReviewReport | None = None,
    ) -> Path:
        """按分析、实现、审查三个时间点生成完整中文审计说明。"""

        machine_reports = ["`capability-report.json`"]
        if interface_report is not None:
            machine_reports.append("`interface-report.json`")
        if review_report is not None:
            machine_reports.append("`review-report.json`")
        lines = [
            f"# {report.target} 测试接口审计报告",
            "",
            "本报告同时列出目标系统已有接口和本次 Agent 生成的接口。",
            "Analyzer 内容描述修改前状态；生成接口和 Reviewer 内容描述候选修改后状态。",
            "机器可读细节以" + "、".join(machine_reports) + "为准。",
            "",
        ]
        implemented = interface_report.capabilities() if interface_report else {}
        for name, title in CAPABILITY_DISPLAY_ORDER:
            finding = report.capabilities[name]
            generated = implemented.get(name)
            lines.extend(
                [f"## {title}", "", f"- 修改前分析状态：`{finding.status.value}`"]
            )
            if finding.boundary:
                lines.append(f"- 覆盖边界：{finding.boundary}")
            lines.append(
                "- 修改前测试接口是否完整："
                + ("是" if finding.existing_test_interface_complete else "否")
            )
            if finding.test_support_reason:
                lines.append(f"- 修改前测试支持判断：{finding.test_support_reason}")
            if generated is not None:
                lines.append(
                    "- 本次修改："
                    + ("已生成接口" if generated.implemented else "实现阶段判定为侵入式")
                )
            lines.append("")

            if finding.execution_paths:
                lines.extend(["### Analyzer 发现的实现路径（修改前）", ""])
                lines.extend(f"- {path}" for path in finding.execution_paths)
                lines.append("")

            if finding.suggested_changes:
                lines.extend(["### Analyzer 建议（修改前）", ""])
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
                    ("缓存实例引用", generated.instance_reference),
                    ("目标绑定方式", generated.target_binding_strategy),
                    ("缓存变化与失败语义", generated.cache_effects),
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
                heading = (
                    "### 修改前已知限制（供对照）"
                    if generated is not None and generated.implemented
                    else "### 当前限制"
                )
                lines.extend([heading, ""])
                lines.extend(f"- {item}" for item in finding.limitations)
                lines.append("")
            elif finding.gap and (generated is None or not generated.implemented):
                lines.extend(["### 当前缺口", "", f"- {finding.gap}", ""])

        if review_report is not None:
            lines.extend(
                [
                    "## 独立 Reviewer 结论",
                    "",
                    f"- 总体结论：`{review_report.overall.value}`",
                    "",
                ]
            )
            if review_report.issues:
                lines.extend(["### 阻塞问题", ""])
                for issue in review_report.issues:
                    location = " / ".join(
                        value for value in (issue.file, issue.symbol) if value
                    )
                    capability = f"[{issue.capability}] " if issue.capability else ""
                    suffix = f"（{location}）" if location else ""
                    lines.append(f"- {capability}{issue.reason}{suffix}")
                lines.append("")
            if review_report.risks:
                lines.extend(["### 非阻塞剩余风险", ""])
                lines.extend(f"- {risk}" for risk in review_report.risks)
                lines.append("")
            if not review_report.issues and not review_report.risks:
                lines.extend(["- Reviewer 未报告阻塞问题或剩余风险。", ""])

        return self.write_text("AUDIT.md", "\n".join(lines).rstrip() + "\n")

    def publish_latest(self) -> Path:
        """原子替换 Git 跟踪的项目级 latest 审计导出。

        patched-worktree 可能包含完整目标仓库和未审核代码，既体积大又不适合
        上传；latest 只复制报告、最终 patch、统计和日志。每个项目拥有独立
        的 ``runs/latest/<project>/``，一次运行不会覆盖其他项目的快照。
        """

        runs_root = self.run_directory.parent
        run_config_path = self.run_directory / "run-config.json"
        if not run_config_path.is_file():
            raise ValueError("cannot publish latest without run-config.json")
        run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
        project_name = run_config.get("project")
        if (
            not isinstance(project_name, str)
            or not project_name
            or project_name in {".", ".."}
            or Path(project_name).name != project_name
        ):
            raise ValueError("run-config project must be a safe directory name")

        latest_root = runs_root / "latest"
        latest = latest_root / project_name
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
                "project": project_name,
                "source_run": self.run_directory.name,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "included": "报告、补丁、统计和日志",
                "excluded": ["patched-worktree*"],
            }
            manifest["experiment"] = run_config.get("experiment")
            (staging / "audit-manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (staging / "APPLY.md").write_text(
                f"""# 应用最近一次已验证补丁

修改目标仓库前，先阅读 `USAGE.md` 和 `AUDIT.md`，再审查
`changes.patch`、`review-report.json` 和 `verification-report.json`，并在
`run-config.json` 中确认目标提交版本。

然后在目标仓库中运行：

```bash
git apply --check /绝对路径/runs/latest/{project_name}/changes.patch
git apply /绝对路径/runs/latest/{project_name}/changes.patch
go test ./...
```

ConsensusSeam 不会自动应用或提交补丁。

如果最近一次运行是 analyze-only，目录中可能没有 `changes.patch`；此时本文件只说明通用应用流程。
""",
                encoding="utf-8",
            )
            latest_root.mkdir(parents=True, exist_ok=True)
            if latest.exists():
                shutil.rmtree(latest)
            os.replace(staging, latest)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return latest
