"""analyze、patch 与完整 run 共用的显式 Controller 状态机。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents import CapabilityAnalyzer, IndependentReviewer, LowIntrusionTransformer
from .config import LoadedPostHocChecks, LoadedProject, ResolvedVerificationFixture
from .languages.go import GoBackend
from .llm.base import AgentRuntime
from .llm.profiles import ModelProfile, resolve_model_profile
from .models import (
    CapabilityCheckConfig,
    CapabilityReport,
    CommandExecution,
    FailureRoute,
    InterfaceReport,
    PatchMetrics,
    ReviewReport,
    ReviewOverall,
    VerificationReport,
    WorkflowOutcome,
    WorkflowResult,
)
from .reporting import ArtifactStore
from .resources import resource_root
from .verify import (
    BaselineVerifier,
    CapabilityCheck,
    DeterministicVerifier,
    materialized_fixtures,
)
from .workspace import GitWorktree, git_audit_state


FORMAL_EXPERIMENT_KINDS = frozenset({"blind_capability", "repair"})


class ExperimentPreconditionError(RuntimeError):
    """正式实验无法绑定到 clean Git revision 时抛出。"""


class RepairInputError(ValueError):
    """原候选产物或生成后 checks 无法形成安全 repair 输入时抛出。"""


@dataclass(frozen=True)
class RepairSource:
    """从既有 run 恢复出的候选接口及其目标版本。"""

    run_directory: Path
    report: CapabilityReport
    interface_report: InterfaceReport
    review_report: ReviewReport
    patch: str
    target_revision: str


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
        artifacts.write_usage(report)
        self._write_unresolved(artifacts, report, project)
        return WorkflowResult(
            outcome=WorkflowOutcome.ANALYZED,
            run_directory=artifacts.run_directory,
        )

    def _with_artifacts(
        self,
        project: LoadedProject,
        operation: Callable[[ArtifactStore], WorkflowResult],
        *,
        run_metadata: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """为所有入口统一管理 run 目录、统计快照和 latest 发布。

        operation 正常返回（即使结果是 FAILED/PARTIAL）才算一次完整工作流，
        可以发布 latest。若 Python/Agent 抛异常，失败目录和统计仍保留，但
        不能用不完整文件覆盖上一次完整审计结果。
        """

        self._require_reproducible_experiment(project)
        artifacts = ArtifactStore.create(self.runs_root)
        self._write_run_config(artifacts, project, extra=run_metadata)
        stats_start = self._runtime_stats_count()
        tool_audit_start = self._runtime_tool_audit_count()
        completed = False
        try:
            result = operation(artifacts)
            completed = True
            return result
        except Exception as exc:
            artifacts.mark_incomplete(type(exc).__name__)
            raise
        finally:
            self._write_runtime_stats(artifacts, stats_start)
            self._write_tool_audit(artifacts, tool_audit_start)
            if completed:
                artifacts.publish_latest()

    def patch(self, project: LoadedProject) -> WorkflowResult:
        """运行 Analyzer→Transformer→Reviewer，但不执行隐藏 Verifier。"""

        return self._patch_loop(project, verify=False)

    def run(self, project: LoadedProject) -> WorkflowResult:
        """对已配置稳定 checks 的目标运行固定评测/回归流程。"""

        return self._patch_loop(project, verify=True)

    def repair(
        self,
        project: LoadedProject,
        *,
        source_run: Path,
        checks: LoadedPostHocChecks,
    ) -> WorkflowResult:
        """用生成后真实测试验证并修复一个已有候选接口。"""

        source = self._load_repair_source(project, source_run, checks)
        return self._with_artifacts(
            project,
            lambda artifacts: self._execute_repair(project, source, checks, artifacts),
            run_metadata={
                "repair": {
                    "source_run": str(source.run_directory),
                    "checks_manifest": str(checks.manifest_path),
                    "target_revision": source.target_revision,
                }
            },
        )

    def _load_repair_source(
        self,
        project: LoadedProject,
        source_run: Path,
        checks: LoadedPostHocChecks,
    ) -> RepairSource:
        """校验原 run 产物、目标 revision 和后置检查范围。"""

        run_directory = source_run.expanduser().resolve()
        if not run_directory.is_dir():
            raise RepairInputError(f"repair source run is not a directory: {run_directory}")

        def read_text(name: str) -> str:
            path = run_directory / name
            try:
                return path.read_text(encoding="utf-8")
            except OSError as exc:
                raise RepairInputError(f"cannot read repair source artifact {path}: {exc}") from exc

        try:
            report = CapabilityReport.model_validate_json(read_text("capability-report.json"))
            interface_report = InterfaceReport.model_validate_json(
                read_text("interface-report.json")
            )
            review_report = ReviewReport.model_validate_json(read_text("review-report.json"))
            run_config = json.loads(read_text("run-config.json"))
        except ValueError as exc:
            raise RepairInputError(f"invalid repair source artifacts: {exc}") from exc
        patch = read_text("changes.patch")
        if not patch.strip():
            raise RepairInputError("repair source changes.patch is empty")
        if report.target != project.manifest.name:
            raise RepairInputError(
                f"repair source target {report.target!r} does not match project "
                f"{project.manifest.name!r}"
            )
        try:
            target_state = run_config["source_revisions"]["target"]
            target_revision = target_state["revision"]
        except (KeyError, TypeError) as exc:
            raise RepairInputError("repair source run-config lacks target revision") from exc
        current_revision = git_audit_state(project.repository)["revision"]
        if not isinstance(target_revision, str) or target_revision != current_revision:
            raise RepairInputError(
                "repair source target revision does not match current target HEAD: "
                f"{target_revision!r} != {current_revision!r}"
            )

        implemented = {
            name
            for name, capability in interface_report.capabilities().items()
            if capability.implemented
        }
        checked = {item.capability for item in checks.manifest.capability_checks}
        unsupported = checked - implemented
        if unsupported:
            raise RepairInputError(
                "post-hoc checks target capabilities absent from the source interface: "
                + ", ".join(sorted(unsupported))
            )
        not_patchable = checked - report.patchable()
        if not_patchable:
            raise RepairInputError(
                "post-hoc repair requires original PATCHABLE findings: "
                + ", ".join(sorted(not_patchable))
            )
        return RepairSource(
            run_directory=run_directory,
            report=report,
            interface_report=interface_report,
            review_report=review_report,
            patch=patch,
            target_revision=target_revision,
        )

    def _execute_repair(
        self,
        project: LoadedProject,
        source: RepairSource,
        posthoc: LoadedPostHocChecks,
        artifacts: ArtifactStore,
    ) -> WorkflowResult:
        """执行后置验证，并在失败时进入有界 Agent 2 修复循环。"""

        baseline = self.baseline_verifier.run(project)
        artifacts.write_model("baseline-report.json", baseline)
        if not baseline.passed:
            return WorkflowResult(
                outcome=WorkflowOutcome.FAILED,
                run_directory=artifacts.run_directory,
                reason="BASELINE_FAILED",
            )

        report = source.report
        current_interface = source.interface_report
        current_patch = source.patch
        artifacts.write_model("capability-report.json", report)
        artifacts.write_model("interface-report.json", current_interface)
        artifacts.write_model("review-report.json", source.review_report)
        artifacts.write_text("changes.patch", current_patch)
        artifacts.write_usage(report, current_interface, source.review_report)
        artifacts.write_json(
            "post-hoc-checks.json",
            posthoc.manifest.model_dump(mode="json"),
        )

        check_configs = posthoc.manifest.capability_checks
        checks = self._capability_checks(check_configs)
        repair_capabilities = {item.capability for item in check_configs}

        initial = GitWorktree.create(
            project.repository,
            artifacts.run_directory / "repair-candidate",
        )
        initial.apply_patch(current_patch)
        protected = initial.modified_existing_go_tests()
        if protected:
            raise RepairInputError(
                "repair source patch modifies existing Go tests: " + ", ".join(protected)
            )
        initial_metrics = initial.patch_metrics()
        artifacts.write_model("patch-metrics.json", initial_metrics)
        initial_verification = self._verify_with_fixtures(
            project,
            initial,
            checks=checks,
            required_capabilities=repair_capabilities,
            fixtures=posthoc.verification_fixtures,
        )
        artifacts.write_model("verification-report.json", initial_verification)
        artifacts.write_model("logs/verification-initial.json", initial_verification)
        if initial_verification.passed:
            self._write_unresolved(artifacts, report, project)
            return WorkflowResult(
                outcome=WorkflowOutcome.PASS,
                run_directory=artifacts.run_directory,
                reason="POST_HOC_CHECKS_PASSED_WITHOUT_REPAIR",
            )
        if initial_verification.route is not FailureRoute.AGENT2:
            self._write_unresolved(artifacts, report, project)
            return WorkflowResult(
                outcome=WorkflowOutcome.PARTIAL,
                run_directory=artifacts.run_directory,
                reason=(
                    initial_verification.failure_code.value
                    if initial_verification.failure_code
                    else "POST_HOC_VERIFICATION_NEEDS_HUMAN"
                ),
            )

        _, transformer, reviewer = self._agents(project)
        feedback: dict[str, Any] = {
            "failure": "POST_HOC_VERIFICATION_FAILED",
            "verification": initial_verification.model_dump(mode="json"),
            "source_run": str(source.run_directory),
            "prior_interface_report": current_interface.model_dump(
                mode="json", exclude_none=True
            ),
            "instruction": (
                "Repair the existing candidate in this worktree. Preserve its public "
                "interface unless the deterministic failure proves that design invalid."
            ),
        }

        for repair_round in range(1, project.manifest.limits.agent2_patch_rounds + 1):
            worktree = GitWorktree.create(
                project.repository,
                artifacts.run_directory / f"repaired-worktree-p{repair_round}",
            )
            worktree.apply_patch(current_patch)
            repaired_subset = self._transform_selected_capabilities(
                project,
                report,
                worktree,
                transformer,
                selected_capabilities=repair_capabilities,
                feedback=feedback,
                invocation_prefix=f"transformer-repair-p{repair_round}",
            )
            artifacts.write_model(
                f"logs/interface-repair-p{repair_round}.json",
                repaired_subset,
            )
            if repaired_subset.rediscovered():
                self._write_unresolved(artifacts, report, project)
                return WorkflowResult(
                    outcome=WorkflowOutcome.PARTIAL,
                    run_directory=artifacts.run_directory,
                    reason="Repair rediscovered an implemented capability as invasive",
                )
            merged_interface = self._merge_interface_reports(
                current_interface,
                repaired_subset,
            )

            protected = worktree.modified_existing_go_tests()
            if protected:
                feedback = {
                    "failure": "EXISTING_TEST_MODIFIED",
                    "files": protected,
                    "instruction": "Repair production code or Agent-created tests only.",
                }
                continue

            format_result, build_result = self._format_and_build_candidate(
                project,
                worktree,
                artifacts,
                label=f"repair-p{repair_round}",
            )
            if not format_result.passed:
                current_patch = worktree.diff()
                current_interface = merged_interface
                feedback = {
                    "failure": "FORMAT_FAILED",
                    "execution": format_result.model_dump(mode="json"),
                    "prior_interface_report": current_interface.model_dump(
                        mode="json", exclude_none=True
                    ),
                }
                continue

            current_patch = worktree.diff()
            current_interface = merged_interface
            if build_result is None or not build_result.passed:
                feedback = {
                    "failure": "BUILD_FAILED",
                    "execution": (
                        None
                        if build_result is None
                        else build_result.model_dump(mode="json")
                    ),
                    "prior_interface_report": current_interface.model_dump(
                        mode="json", exclude_none=True
                    ),
                }
                continue

            current_patch, _, review = self._review_candidate(
                project,
                report,
                current_interface,
                worktree,
                reviewer,
                artifacts,
                label=f"repair-p{repair_round}",
                invocation_id=f"reviewer-repair-p{repair_round}",
            )
            if review.overall is ReviewOverall.REVISE_AGENT2:
                feedback = review.model_dump(mode="json")
                continue
            if review.overall is not ReviewOverall.PASS:
                self._write_unresolved(artifacts, report, project)
                return WorkflowResult(
                    outcome=WorkflowOutcome.PARTIAL,
                    run_directory=artifacts.run_directory,
                    reason="Repair review requires analysis or human judgment",
                )

            verification = self._verify_with_fixtures(
                project,
                worktree,
                checks=checks,
                required_capabilities=repair_capabilities,
                fixtures=posthoc.verification_fixtures,
            )
            artifacts.write_model("verification-report.json", verification)
            artifacts.write_model(
                f"logs/verification-repair-p{repair_round}.json",
                verification,
            )
            if verification.passed:
                self._write_unresolved(artifacts, report, project)
                return WorkflowResult(
                    outcome=WorkflowOutcome.REPAIRED,
                    run_directory=artifacts.run_directory,
                )
            if verification.route is FailureRoute.AGENT2:
                feedback = {
                    "failure": "POST_HOC_VERIFICATION_FAILED",
                    "verification": verification.model_dump(mode="json"),
                    "prior_interface_report": current_interface.model_dump(
                        mode="json", exclude_none=True
                    ),
                }
                continue
            self._write_unresolved(artifacts, report, project)
            return WorkflowResult(
                outcome=WorkflowOutcome.PARTIAL,
                run_directory=artifacts.run_directory,
                reason=(
                    verification.failure_code.value
                    if verification.failure_code
                    else "POST_HOC_VERIFICATION_NEEDS_HUMAN"
                ),
            )

        self._write_unresolved(artifacts, report, project)
        return WorkflowResult(
            outcome=WorkflowOutcome.FAILED,
            run_directory=artifacts.run_directory,
            reason="Agent 2 repair budget exhausted",
        )

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
        artifacts.write_usage(report)
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
                artifacts.write_usage(report)
                if not self._selected_patchable(project, report):
                    self._write_unresolved(artifacts, report, project)
                    return WorkflowResult(
                        outcome=WorkflowOutcome.NO_PATCH_NEEDED,
                        run_directory=artifacts.run_directory,
                        reason="Reanalysis found no safely patchable capability",
                    )

            requested_reanalysis = False
            agent2_feedback: dict[str, Any] | None = None
            # build、Reviewer 或 Verifier 要求 Agent 2 修订时，下一轮仍从
            # clean HEAD 创建 worktree，但先重放上一版候选。这样保留已审查
            # 的接口设计，同时不继承原工作目录中的非 Git 残留状态。
            prior_candidate_patch: str | None = None
            prior_interface_report: InterfaceReport | None = None
            selected_capabilities = self._selected_patchable(project, report)
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
                if prior_candidate_patch is not None:
                    worktree.apply_patch(prior_candidate_patch)
                revised_interface = self._transform_selected_capabilities(
                    project,
                    report,
                    worktree,
                    transformer,
                    selected_capabilities=selected_capabilities,
                    feedback=agent2_feedback,
                    invocation_prefix=f"transformer-a{analysis_round}-p{patch_round}",
                )
                interface_report = (
                    revised_interface
                    if prior_interface_report is None
                    else self._merge_interface_reports(
                        prior_interface_report,
                        revised_interface,
                    )
                )
                artifacts.write_model("interface-report.json", interface_report)
                artifacts.write_usage(report, interface_report)
                artifacts.write_model(
                    f"logs/interface-a{analysis_round}-p{patch_round}.json",
                    interface_report,
                )

                rediscovered = interface_report.rediscovered()
                if rediscovered:
                    # 实作阶段发现侵入性时，整个候选 worktree 作废；只把状态
                    # 合并回报告，再从 HEAD 处理剩余 PATCHABLE 能力。
                    report.apply_rediscovered(rediscovered)
                    prior_candidate_patch = None
                    prior_interface_report = None
                    artifacts.write_model("capability-report.json", report)
                    artifacts.write_usage(report, interface_report)
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
                    selected_capabilities = self._selected_patchable(project, report)
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
                    prior_candidate_patch = None
                    prior_interface_report = None
                    agent2_feedback = {
                        "failure": "EXISTING_TEST_MODIFIED",
                        "files": protected_tests,
                        "instruction": (
                            "The prior worktree was discarded. Existing Go tests are "
                            "immutable; create new capability tests instead."
                        ),
                    }
                    selected_capabilities = self._selected_patchable(project, report)
                    continue

                label = f"a{analysis_round}-p{patch_round}"
                format_result, build_result = self._format_and_build_candidate(
                    project,
                    worktree,
                    artifacts,
                    label=label,
                )
                if not format_result.passed:
                    prior_candidate_patch = worktree.diff()
                    prior_interface_report = interface_report
                    agent2_feedback = {
                        "failure": "FORMAT_FAILED",
                        "execution": format_result.model_dump(mode="json"),
                        "prior_interface_report": interface_report.model_dump(
                            mode="json", exclude_none=True
                        ),
                        "instruction": (
                            "The prior candidate is already applied in the fresh "
                            "worktree. Revise it instead of regenerating from HEAD."
                        ),
                    }
                    continue

                if build_result is None or not build_result.passed:
                    prior_candidate_patch = worktree.diff()
                    prior_interface_report = interface_report
                    agent2_feedback = {
                        "failure": "BUILD_FAILED",
                        "execution": (
                            None
                            if build_result is None
                            else build_result.model_dump(mode="json")
                        ),
                        "prior_interface_report": interface_report.model_dump(
                            mode="json", exclude_none=True
                        ),
                        "instruction": (
                            "The prior candidate is already applied in the fresh "
                            "worktree. Revise it instead of regenerating from HEAD."
                        ),
                    }
                    continue

                git_diff, _, review = self._review_candidate(
                    project,
                    report,
                    interface_report,
                    worktree,
                    reviewer,
                    artifacts,
                    label=label,
                    invocation_id=f"reviewer-a{analysis_round}-p{patch_round}",
                )
                prior_candidate_patch = git_diff

                if review.overall is ReviewOverall.REVISE_AGENT1:
                    # 语义边界/能力分类错误才回到 Analyzer。
                    agent1_feedback = review.model_dump(mode="json")
                    requested_reanalysis = True
                    break
                if review.overall is ReviewOverall.REVISE_AGENT2:
                    # 实现问题在下一 fresh worktree 中基于当前候选修订。
                    prior_interface_report = interface_report
                    selected_capabilities = self._review_revision_capabilities(
                        review,
                        available=self._selected_patchable(project, report),
                    )
                    agent2_feedback = {
                        "failure": "REVIEW_REVISE_AGENT2",
                        "review": review.model_dump(mode="json"),
                        "prior_interface_report": interface_report.model_dump(
                            mode="json", exclude_none=True
                        ),
                        "instruction": (
                            "The reviewed candidate is already applied in the fresh "
                            "worktree. Resolve every blocking issue, keep valid public "
                            "interfaces stable, and update post-change limitations."
                        ),
                    }
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

                checks = self._capability_checks(project.manifest.capability_checks)
                implemented = {
                    name
                    for name, capability in interface_report.capabilities().items()
                    if capability.implemented
                }
                verification = self._verify_with_fixtures(
                    project,
                    worktree,
                    checks=checks,
                    required_capabilities=implemented,
                    fixtures=project.verification_fixtures,
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
                    prior_interface_report = interface_report
                    agent2_feedback = {
                        "failure": "DETERMINISTIC_VERIFICATION_FAILED",
                        "verification": verification.model_dump(mode="json"),
                        "prior_interface_report": interface_report.model_dump(
                            mode="json", exclude_none=True
                        ),
                        "instruction": (
                            "The verified candidate is already applied in the fresh "
                            "worktree. Repair the implementation without changing "
                            "evaluator-provided tests."
                        ),
                    }
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

    def _format_and_build_candidate(
        self,
        project: LoadedProject,
        worktree: GitWorktree,
        artifacts: ArtifactStore,
        *,
        label: str,
    ) -> tuple[CommandExecution, CommandExecution | None]:
        """统一格式化候选并执行项目 build，供 patch/repair 共用。"""

        worktree.diff()
        format_result = self.backend.format_changed_files(worktree.path)
        artifacts.write_model(f"logs/format-{label}.json", format_result)
        if not format_result.passed:
            return format_result, None
        patched_workdir = worktree.path / project.working_directory.relative_to(
            project.repository
        )
        build_result = self.backend.build(
            patched_workdir,
            project.manifest.build.command,
        )
        artifacts.write_model(f"logs/build-{label}.json", build_result)
        return format_result, build_result

    @staticmethod
    def _review_candidate(
        project: LoadedProject,
        report: CapabilityReport,
        interface_report: InterfaceReport,
        worktree: GitWorktree,
        reviewer: IndependentReviewer,
        artifacts: ArtifactStore,
        *,
        label: str,
        invocation_id: str,
    ) -> tuple[str, PatchMetrics, ReviewReport]:
        """统一导出候选 patch/metrics，并执行独立 Reviewer。"""

        git_diff = worktree.diff()
        patch_metrics = worktree.patch_metrics()
        artifacts.write_text("changes.patch", git_diff)
        artifacts.write_model("patch-metrics.json", patch_metrics)
        artifacts.write_model("interface-report.json", interface_report)
        review = reviewer.review(
            project,
            report,
            interface_report,
            worktree.path,
            git_diff,
            patch_metrics,
            invocation_id=invocation_id,
        )
        artifacts.write_model("review-report.json", review)
        artifacts.write_model(f"logs/review-{label}.json", review)
        artifacts.write_usage(report, interface_report, review)
        return git_diff, patch_metrics, review

    @staticmethod
    def _capability_checks(
        configs: list[CapabilityCheckConfig],
    ) -> list[CapabilityCheck]:
        """把 manifest 模型转换为 Verifier 的不可变运行描述。"""

        return [
            CapabilityCheck(
                name=item.name,
                capability=item.capability,
                command=item.command,
                failure_code=item.failure_code,
            )
            for item in configs
        ]

    def _verify_with_fixtures(
        self,
        project: LoadedProject,
        worktree: GitWorktree,
        *,
        checks: list[CapabilityCheck],
        required_capabilities: set[str],
        fixtures: tuple[ResolvedVerificationFixture, ...],
    ) -> VerificationReport:
        """在 Reviewer 之后短暂物化 fixture 并执行统一 Verifier。"""

        base = self.verifier.verify_base(project, worktree.path)
        if not base.passed:
            return base
        with materialized_fixtures(fixtures, worktree.path):
            return self.verifier.verify_capabilities(
                project,
                worktree.path,
                base=base,
                capability_checks=checks,
                required_capabilities=required_capabilities,
            )

    @staticmethod
    def _merge_interface_reports(
        existing: InterfaceReport,
        repaired: InterfaceReport,
    ) -> InterfaceReport:
        """用本轮修复子集替换原报告对应能力，保留未测试能力。"""

        merged = existing.model_copy(deep=True)
        for name, capability in repaired.capabilities().items():
            setattr(merged, name, capability)
        return merged

    @staticmethod
    def _review_revision_capabilities(
        review: ReviewReport,
        *,
        available: set[str],
    ) -> set[str]:
        """只重跑 Reviewer 阻塞问题涉及的能力，并保持消息控制成组。"""

        selected = {
            issue.capability
            for issue in review.issues
            if issue.capability is not None and issue.capability in available
        }
        if not selected:
            # Reviewer 可能只能定位到文件而不能可靠归属能力；此时保守地
            # 修订全部可用能力，不能擅自忽略阻塞问题。
            return set(available)
        message_control = {"message_capture", "message_injection"}
        if selected & message_control:
            selected |= available & message_control
        return selected

    def _transform_selected_capabilities(
        self,
        project: LoadedProject,
        report: CapabilityReport,
        worktree: GitWorktree,
        transformer: LowIntrusionTransformer,
        *,
        selected_capabilities: set[str],
        feedback: dict[str, Any] | None,
        invocation_prefix: str,
    ) -> InterfaceReport:
        """按实现单元拆分 Agent 2 调用，并在同一 worktree 中累积修改。

        大多数能力是独立研究单位；消息捕获和消息注入则共同定义同一缓存
        控制面。当两者同时被选择时必须交给同一次 Transformer 调用，避免
        分别生成彼此无关的缓存和入口。其余能力仍逐项调用，控制大型目标的
        源码探索与编辑预算。
        """

        combined: InterfaceReport | None = None
        remaining = set(selected_capabilities)
        units: list[tuple[str, set[str]]] = []
        message_control = {"message_capture", "message_injection"}
        if message_control <= remaining:
            units.append(("message_control", message_control))
            remaining -= message_control
        units.extend((capability, {capability}) for capability in sorted(remaining))

        for unit_name, capabilities in units:
            partial = transformer.transform(
                project,
                report,
                worktree.path,
                selected_capabilities=capabilities,
                feedback=feedback,
                invocation_id=f"{invocation_prefix}-{unit_name}",
            )
            combined = (
                partial
                if combined is None
                else self._merge_interface_reports(combined, partial)
            )
            # 发现侵入性后，调用方会丢弃整个候选；无需让其余能力继续产生
            # 无法保留的修改和模型成本。
            if partial.rediscovered():
                break
        if combined is None:
            raise ValueError("Transformer requires at least one selected capability")
        return combined

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

    def _write_run_config(
        self,
        artifacts: ArtifactStore,
        project: LoadedProject,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """记录复现实验所需的提交、模型、边界和 Controller-only 配置。"""

        models = resolve_model_profile(project.manifest.llm, self.model_profile)
        payload: dict[str, Any] = {
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
        }
        if extra:
            payload.update(extra)
        artifacts.write_json("run-config.json", payload)

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
