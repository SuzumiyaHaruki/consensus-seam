"""Explicit controller state machine for analyze, patch, and full runs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .agents import CapabilityAnalyzer, IndependentReviewer, LowIntrusionTransformer
from .config import LoadedProject
from .languages.go import GoBackend
from .llm.base import AgentRuntime
from .llm.profiles import ModelProfile, resolve_model_profile
from .models import (
    CapabilityReport,
    FailureRoute,
    ReviewOverall,
    WorkflowOutcome,
    WorkflowResult,
)
from .reporting import ArtifactStore
from .resources import resource_root
from .verify import (
    BaselineVerifier,
    CapabilityCheck,
    DeterministicVerifier,
    materialized_verification_fixtures,
)
from .workspace import GitWorktree, git_audit_state


FORMAL_EXPERIMENT_KINDS = frozenset({"blind_capability", "repair"})


class ExperimentPreconditionError(RuntimeError):
    """正式实验无法绑定到 clean Git revision 时抛出。"""


class ConsensusWorkflow:
    """以固定、可审计的状态机编排三个 Agent 和 Verifier。

    Agent 只负责各自角色内的判断；是否重试、路由给谁、最多执行几轮都由
    本类的普通 Python 控制流决定，避免让另一个 Agent 动态发明工作流。
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        runs_root: Path,
        backend: GoBackend | None = None,
        model_profile: ModelProfile = "manifest",
        controller_repository: Path | None = None,
    ) -> None:
        # 同一个 backend 同时交给 Agent 工具、baseline 和 verifier，确保
        # 各阶段对目标语言命令的解释一致。
        self.backend = backend or GoBackend()
        self.runtime = runtime
        self.model_profile = model_profile
        self.baseline_verifier = BaselineVerifier(self.backend)
        self.verifier = DeterministicVerifier(self.backend)
        self.runs_root = runs_root
        self.controller_repository = (
            controller_repository or resource_root()
        ).resolve()

    def analyze(self, project: LoadedProject) -> WorkflowResult:
        """只运行只读 Analyzer，不创建 patch worktree。"""

        return self._with_artifacts(
            project,
            lambda artifacts: self._execute_analysis(project, artifacts),
        )

    def _execute_analysis(
        self,
        project: LoadedProject,
        artifacts: ArtifactStore,
    ) -> WorkflowResult:
        # analyze-only 仍使用 a1/attemptN 命名，保证统计格式与完整运行一致。
        analyzer, _, _ = self._agents(project)
        report = analyzer.analyze(project, invocation_id="analyzer-a1")
        artifacts.write_model("capability-report.json", report)
        self._write_unresolved(artifacts, report, project)
        return WorkflowResult(
            outcome=WorkflowOutcome.ANALYZED,
            run_directory=artifacts.run_directory,
        )

    def _with_artifacts(
        self,
        project: LoadedProject,
        operation: Callable[[ArtifactStore], WorkflowResult],
    ) -> WorkflowResult:
        """为所有入口统一管理 run 目录、统计快照和 latest 发布。

        operation 正常返回（即使结果是 FAILED/PARTIAL）才算一次完整工作流，
        可以发布 latest。若 Python/Agent 抛异常，失败目录和统计仍保留，但
        不能用不完整文件覆盖上一次完整审计结果。
        """

        self._require_reproducible_experiment(project)
        artifacts = ArtifactStore.create(self.runs_root)
        self._write_run_config(artifacts, project)
        stats_start = self._runtime_stats_count()
        tool_audit_start = self._runtime_tool_audit_count()
        completed = False
        try:
            result = operation(artifacts)
            completed = True
            return result
        finally:
            self._write_runtime_stats(artifacts, stats_start)
            self._write_tool_audit(artifacts, tool_audit_start)
            if completed:
                artifacts.publish_latest()

    def patch(self, project: LoadedProject) -> WorkflowResult:
        """运行 Analyzer→Transformer→Reviewer，但不执行隐藏 Verifier。"""

        return self._patch_loop(project, verify=False)

    def run(self, project: LoadedProject) -> WorkflowResult:
        """运行 baseline、三个 Agent 和全部确定性能力检查。"""

        return self._patch_loop(project, verify=True)

    def _patch_loop(self, project: LoadedProject, *, verify: bool) -> WorkflowResult:
        return self._with_artifacts(
            project,
            lambda artifacts: self._execute_patch_loop(
                project,
                verify=verify,
                artifacts=artifacts,
            ),
        )

    def _execute_patch_loop(
        self,
        project: LoadedProject,
        *,
        verify: bool,
        artifacts: ArtifactStore,
    ) -> WorkflowResult:
        """执行有界的 analysis-round / patch-round 双层循环。"""

        analyzer, transformer, reviewer = self._agents(project)
        if verify:
            # 原始仓库若已经构建/测试失败，就无法把候选失败归因给 Agent 2。
            baseline = self.baseline_verifier.run(project)
            artifacts.write_model("baseline-report.json", baseline)
            if not baseline.passed:
                return WorkflowResult(
                    outcome=WorkflowOutcome.FAILED,
                    run_directory=artifacts.run_directory,
                    reason="BASELINE_FAILED",
                )

        report = analyzer.analyze(project, invocation_id="analyzer-a1")
        artifacts.write_model("capability-report.json", report)
        # Analyzer 始终分析全部能力；实验 allowlist 只限制 Transformer。
        if not self._selected_patchable(project, report):
            self._write_unresolved(artifacts, report, project)
            reason = (
                "No PATCHABLE capability selected by transform_capabilities"
                if report.patchable()
                else "No capability was classified PATCHABLE"
            )
            return WorkflowResult(
                outcome=WorkflowOutcome.NO_PATCH_NEEDED,
                run_directory=artifacts.run_directory,
                reason=reason,
            )

        agent1_feedback: dict[str, Any] | None = None
        limits = project.manifest.limits
        for analysis_round in range(1, limits.agent1_reanalysis_rounds + 1):
            if analysis_round > 1:
                # 只有 Reviewer/Verifier 明确路由 AGENT1 时才重新分析；普通
                # build 或 capability test 失败只应要求 Agent 2 修补实现。
                report = analyzer.analyze(
                    project,
                    feedback=agent1_feedback,
                    invocation_id=f"analyzer-a{analysis_round}",
                )
                artifacts.write_model("capability-report.json", report)
                if not self._selected_patchable(project, report):
                    self._write_unresolved(artifacts, report, project)
                    return WorkflowResult(
                        outcome=WorkflowOutcome.NO_PATCH_NEEDED,
                        run_directory=artifacts.run_directory,
                        reason="Reanalysis found no safely patchable capability",
                    )

            requested_reanalysis = False
            agent2_feedback: dict[str, Any] | None = None
            for patch_round in range(1, limits.agent2_patch_rounds + 1):
                # 每个 patch round 都从目标 HEAD 创建全新 worktree，失败候选
                # 的残留文件不会进入下一轮。
                worktree_name = (
                    "patched-worktree"
                    if analysis_round == 1 and patch_round == 1
                    else f"patched-worktree-a{analysis_round}-p{patch_round}"
                )
                worktree = GitWorktree.create(
                    project.repository,
                    artifacts.run_directory / worktree_name,
                )
                interface_report = transformer.transform(
                    project,
                    report,
                    worktree.path,
                    selected_capabilities=self._selected_patchable(project, report),
                    feedback=agent2_feedback,
                    invocation_id=f"transformer-a{analysis_round}-p{patch_round}",
                )
                artifacts.write_model("interface-report.json", interface_report)
                artifacts.write_model(
                    f"logs/interface-a{analysis_round}-p{patch_round}.json",
                    interface_report,
                )

                rediscovered = interface_report.rediscovered()
                if rediscovered:
                    # 实作阶段发现侵入性时，整个候选 worktree 作废；只把状态
                    # 合并回报告，再从 HEAD 处理剩余 PATCHABLE 能力。
                    report.apply_rediscovered(rediscovered)
                    artifacts.write_model("capability-report.json", report)
                    artifacts.write_json(
                        f"logs/discarded-a{analysis_round}-p{patch_round}.json",
                        {
                            "worktree": str(worktree.path),
                            "reason": "INVASIVE_REDISCOVERED",
                            "capabilities": sorted(rediscovered),
                        },
                    )
                    if not self._selected_patchable(project, report):
                        artifacts.write_text("changes.patch", "")
                        self._write_unresolved(artifacts, report, project)
                        return WorkflowResult(
                            outcome=WorkflowOutcome.PARTIAL,
                            run_directory=artifacts.run_directory,
                            reason="All proposed changes were rediscovered as invasive",
                        )
                    agent2_feedback = {
                        "failure": "INVASIVE_REDISCOVERED",
                        "discarded_capabilities": sorted(rediscovered),
                        "instruction": (
                            "The prior worktree was discarded. Start from the fresh "
                            "worktree and modify only remaining PATCHABLE capabilities."
                        ),
                    }
                    continue

                protected_tests = worktree.modified_existing_go_tests()
                if protected_tests:
                    # Agent 2 可以新增能力测试，但不能通过修改已有测试来让
                    # 回归套件变得更容易通过。
                    artifacts.write_json(
                        f"logs/protected-files-a{analysis_round}-p{patch_round}.json",
                        {
                            "worktree": str(worktree.path),
                            "reason": "EXISTING_TEST_MODIFIED",
                            "files": protected_tests,
                        },
                    )
                    agent2_feedback = {
                        "failure": "EXISTING_TEST_MODIFIED",
                        "files": protected_tests,
                        "instruction": (
                            "The prior worktree was discarded. Existing Go tests are "
                            "immutable; create new capability tests instead."
                        ),
                    }
                    continue

                # intent-to-add 让新文件出现在普通 git diff 中；随后只格式化
                # 实际变化的 Go 文件。
                worktree.diff()
                format_result = self.backend.format_changed_files(worktree.path)
                artifacts.write_model(
                    f"logs/format-a{analysis_round}-p{patch_round}.json",
                    format_result,
                )
                if not format_result.passed:
                    agent2_feedback = {
                        "failure": "FORMAT_FAILED",
                        "execution": format_result.model_dump(mode="json"),
                    }
                    continue

                relative_workdir = project.working_directory.relative_to(project.repository)
                patched_workdir = worktree.path / relative_workdir
                build_result = self.backend.build(
                    patched_workdir,
                    project.manifest.build.command,
                )
                artifacts.write_model(
                    f"logs/build-a{analysis_round}-p{patch_round}.json",
                    build_result,
                )
                if not build_result.passed:
                    agent2_feedback = {
                        "failure": "BUILD_FAILED",
                        "execution": build_result.model_dump(mode="json"),
                    }
                    continue

                git_diff = worktree.diff()
                artifacts.write_text("changes.patch", git_diff)
                patch_metrics = worktree.patch_metrics()
                artifacts.write_model("patch-metrics.json", patch_metrics)
                review = reviewer.review(
                    project,
                    report,
                    interface_report,
                    worktree.path,
                    git_diff,
                    patch_metrics,
                    invocation_id=f"reviewer-a{analysis_round}-p{patch_round}",
                )
                artifacts.write_model("review-report.json", review)
                artifacts.write_model(
                    f"logs/review-a{analysis_round}-p{patch_round}.json",
                    review,
                )

                if review.overall is ReviewOverall.REVISE_AGENT1:
                    # 语义边界/能力分类错误才回到 Analyzer。
                    agent1_feedback = review.model_dump(mode="json")
                    requested_reanalysis = True
                    break
                if review.overall is ReviewOverall.REVISE_AGENT2:
                    # 实现问题在下一 fresh worktree 中由 Transformer 修订。
                    agent2_feedback = review.model_dump(mode="json")
                    continue
                if review.overall is ReviewOverall.NEEDS_HUMAN:
                    self._write_unresolved(artifacts, report, project)
                    return WorkflowResult(
                        outcome=WorkflowOutcome.PARTIAL,
                        run_directory=artifacts.run_directory,
                        reason="Independent review requires human judgment",
                    )

                if not verify:
                    # patch 命令到静态审查通过即结束；只有 run 才执行 oracle。
                    self._write_unresolved(artifacts, report, project)
                    return WorkflowResult(
                        outcome=WorkflowOutcome.PASS,
                        run_directory=artifacts.run_directory,
                    )

                checks = [
                    CapabilityCheck(
                        name=item.name,
                        capability=item.capability,
                        command=item.command,
                        failure_code=item.failure_code,
                    )
                    for item in project.manifest.capability_checks
                ]
                implemented = {
                    name
                    for name, capability in interface_report.capabilities().items()
                    if capability.implemented
                }
                # 隐藏 fixture 直到 Agent 3 完成才短暂出现，并由 context
                # manager 在任何成功/异常路径上删除。
                with materialized_verification_fixtures(project, worktree.path):
                    verification = self.verifier.verify(
                        project,
                        worktree.path,
                        capability_checks=checks,
                        required_capabilities=implemented,
                    )
                artifacts.write_model("verification-report.json", verification)
                artifacts.write_model(
                    f"logs/verification-a{analysis_round}-p{patch_round}.json",
                    verification,
                )
                if verification.passed:
                    self._write_unresolved(artifacts, report, project)
                    return WorkflowResult(
                        outcome=WorkflowOutcome.PASS,
                        run_directory=artifacts.run_directory,
                    )
                if verification.route is FailureRoute.AGENT2:
                    # 传回的是确定性命令、退出码和失败类型，而不是隐藏源码。
                    agent2_feedback = verification.model_dump(mode="json")
                    continue
                self._write_unresolved(artifacts, report, project)
                return WorkflowResult(
                    outcome=WorkflowOutcome.PARTIAL,
                    run_directory=artifacts.run_directory,
                    reason=verification.failure_code.value if verification.failure_code else None,
                )

            if requested_reanalysis:
                continue
            self._write_unresolved(artifacts, report, project)
            return WorkflowResult(
                outcome=WorkflowOutcome.FAILED,
                run_directory=artifacts.run_directory,
                reason="Agent 2 patch budget exhausted",
            )

        self._write_unresolved(artifacts, report, project)
        return WorkflowResult(
            outcome=WorkflowOutcome.FAILED,
            run_directory=artifacts.run_directory,
            reason="Agent 1 reanalysis budget exhausted",
        )

    def _agents(
        self,
        project: LoadedProject,
    ) -> tuple[CapabilityAnalyzer, LowIntrusionTransformer, IndependentReviewer]:
        """按当前模型 profile 创建本次运行使用的三个角色实例。"""

        models = resolve_model_profile(project.manifest.llm, self.model_profile)
        return (
            CapabilityAnalyzer(
                self.runtime,
                model=models.analyzer,
                backend=self.backend,
            ),
            LowIntrusionTransformer(
                self.runtime,
                model=models.transformer,
                backend=self.backend,
            ),
            IndependentReviewer(
                self.runtime,
                model=models.reviewer,
                backend=self.backend,
            ),
        )

    def _write_run_config(self, artifacts: ArtifactStore, project: LoadedProject) -> None:
        """记录复现实验所需的提交、模型、边界和 Controller-only 配置。"""

        models = resolve_model_profile(project.manifest.llm, self.model_profile)
        artifacts.write_json(
            "run-config.json",
            {
                "project": project.manifest.name,
                "experiment": (
                    None
                    if project.manifest.experiment is None
                    else project.manifest.experiment.model_dump(mode="json")
                ),
                "source_revisions": {
                    "controller": git_audit_state(self.controller_repository),
                    "target": git_audit_state(project.repository),
                },
                "system_boundary": project.manifest.system_boundary.model_dump(mode="json"),
                "model_profile": self.model_profile,
                "transform_capabilities": project.manifest.transform_capabilities,
                "resolved_models": models.model_dump(mode="json"),
                "capability_checks": [
                    check.model_dump(mode="json")
                    for check in project.manifest.capability_checks
                ],
                "verification_fixtures": [
                    fixture.model_dump(mode="json")
                    for fixture in project.manifest.verification_fixtures
                ],
            },
        )

    def _require_reproducible_experiment(self, project: LoadedProject) -> None:
        """正式 blind/repair 实验必须从两个 clean Git revision 启动。

        普通开发 smoke 不受此限制。正式实验若允许 dirty tree，run-config
        中的 commit 无法唯一确定真正执行的 Controller/Target 源码。
        """

        experiment = project.manifest.experiment
        if experiment is None or experiment.kind not in FORMAL_EXPERIMENT_KINDS:
            return
        states = {
            "controller": git_audit_state(self.controller_repository),
            "target": git_audit_state(project.repository),
        }
        invalid = [
            name
            for name, state in states.items()
            if state["revision"] is None or state["dirty"] is not False
        ]
        if invalid:
            details = ", ".join(
                f"{name}(revision={states[name]['revision']}, dirty={states[name]['dirty']})"
                for name in invalid
            )
            raise ExperimentPreconditionError(
                "formal experiments require clean Git revisions: " + details
            )

    def _runtime_stats_count(self) -> int:
        # Fake runtime 没有统计接口；getattr 让开发适配器无需伪造空实现。
        snapshot = getattr(self.runtime, "stats_snapshot", None)
        return len(snapshot()) if callable(snapshot) else 0

    def _write_runtime_stats(self, artifacts: ArtifactStore, start: int) -> None:
        # Runtime 可被多个 workflow 复用，因此只写本次调用开始后的增量。
        snapshot = getattr(self.runtime, "stats_snapshot", None)
        records = snapshot()[start:] if callable(snapshot) else []
        artifacts.write_json("agent-run-stats.json", records)

    def _runtime_tool_audit_count(self) -> int:
        snapshot = getattr(self.runtime, "tool_audit_snapshot", None)
        return len(snapshot()) if callable(snapshot) else 0

    def _write_tool_audit(self, artifacts: ArtifactStore, start: int) -> None:
        snapshot = getattr(self.runtime, "tool_audit_snapshot", None)
        records = snapshot()[start:] if callable(snapshot) else []
        artifacts.write_json("tool-call-audit.json", records)

    @staticmethod
    def _selected_patchable(
        project: LoadedProject,
        report: CapabilityReport,
    ) -> set[str]:
        """计算分析结论与本次 transform allowlist 的交集。"""

        return report.patchable(project.manifest.transform_capabilities)

    @staticmethod
    def _write_unresolved(
        artifacts: ArtifactStore,
        report: CapabilityReport,
        project: LoadedProject,
    ) -> None:
        artifacts.write_unresolved(
            report,
            transform_capabilities=project.manifest.transform_capabilities,
        )
