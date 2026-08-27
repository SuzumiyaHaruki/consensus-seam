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


class ConsensusWorkflow:
    """Orchestrate Agents with fixed transitions and bounded retries."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        runs_root: Path,
        backend: GoBackend | None = None,
        model_profile: ModelProfile = "manifest",
    ) -> None:
        self.backend = backend or GoBackend()
        self.runtime = runtime
        self.model_profile = model_profile
        self.baseline_verifier = BaselineVerifier(self.backend)
        self.verifier = DeterministicVerifier(self.backend)
        self.runs_root = runs_root

    def analyze(self, project: LoadedProject) -> WorkflowResult:
        return self._with_artifacts(
            project,
            lambda artifacts: self._execute_analysis(project, artifacts),
        )

    def _execute_analysis(
        self,
        project: LoadedProject,
        artifacts: ArtifactStore,
    ) -> WorkflowResult:
        analyzer, _, _ = self._agents(project)
        report = analyzer.analyze(project)
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
        artifacts = ArtifactStore.create(self.runs_root)
        self._write_run_config(artifacts, project)
        stats_start = self._runtime_stats_count()
        tool_audit_start = self._runtime_tool_audit_count()
        try:
            return operation(artifacts)
        finally:
            self._write_runtime_stats(artifacts, stats_start)
            self._write_tool_audit(artifacts, tool_audit_start)
            artifacts.publish_latest()

    def patch(self, project: LoadedProject) -> WorkflowResult:
        return self._patch_loop(project, verify=False)

    def run(self, project: LoadedProject) -> WorkflowResult:
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
        analyzer, transformer, reviewer = self._agents(project)
        if verify:
            baseline = self.baseline_verifier.run(project)
            artifacts.write_model("baseline-report.json", baseline)
            if not baseline.passed:
                return WorkflowResult(
                    outcome=WorkflowOutcome.FAILED,
                    run_directory=artifacts.run_directory,
                    reason="BASELINE_FAILED",
                )

        report = analyzer.analyze(project)
        artifacts.write_model("capability-report.json", report)
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
                report = analyzer.analyze(project, feedback=agent1_feedback)
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
                )
                artifacts.write_model("interface-report.json", interface_report)
                artifacts.write_model(
                    f"logs/interface-a{analysis_round}-p{patch_round}.json",
                    interface_report,
                )

                rediscovered = interface_report.rediscovered()
                if rediscovered:
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

                # Make new files visible to Git before selecting changed Go files.
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
                )
                artifacts.write_model("review-report.json", review)
                artifacts.write_model(
                    f"logs/review-a{analysis_round}-p{patch_round}.json",
                    review,
                )

                if review.overall is ReviewOverall.REVISE_AGENT1:
                    agent1_feedback = review.model_dump(mode="json")
                    requested_reanalysis = True
                    break
                if review.overall is ReviewOverall.REVISE_AGENT2:
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
                    "controller": git_audit_state(resource_root()),
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

    def _runtime_stats_count(self) -> int:
        snapshot = getattr(self.runtime, "stats_snapshot", None)
        return len(snapshot()) if callable(snapshot) else 0

    def _write_runtime_stats(self, artifacts: ArtifactStore, start: int) -> None:
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
