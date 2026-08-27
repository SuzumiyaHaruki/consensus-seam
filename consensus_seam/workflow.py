"""Explicit controller state machine for analyze, patch, and full runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agents import CapabilityAnalyzer, IndependentReviewer, LowIntrusionTransformer
from .config import LoadedProject
from .languages.go import GoBackend
from .llm.base import AgentRuntime
from .llm.profiles import ModelProfile, resolve_model_profile
from .models import (
    FailureRoute,
    ReviewOverall,
    WorkflowOutcome,
    WorkflowResult,
)
from .reporting import ArtifactStore
from .verify import BaselineVerifier, CapabilityCheck, DeterministicVerifier
from .workspace import GitWorktree


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
        artifacts = ArtifactStore.create(self.runs_root)
        self._write_run_config(artifacts, project)
        stats_start = self._runtime_stats_count()
        try:
            analyzer, _, _ = self._agents(project)
            report = analyzer.analyze(project)
            artifacts.write_model("capability-report.json", report)
            artifacts.write_unresolved(report)
            return WorkflowResult(
                outcome=WorkflowOutcome.ANALYZED,
                run_directory=artifacts.run_directory,
            )
        finally:
            self._write_runtime_stats(artifacts, stats_start)

    def patch(self, project: LoadedProject) -> WorkflowResult:
        return self._patch_loop(project, verify=False)

    def run(self, project: LoadedProject) -> WorkflowResult:
        return self._patch_loop(project, verify=True)

    def _patch_loop(self, project: LoadedProject, *, verify: bool) -> WorkflowResult:
        artifacts = ArtifactStore.create(self.runs_root)
        self._write_run_config(artifacts, project)
        stats_start = self._runtime_stats_count()
        try:
            return self._execute_patch_loop(project, verify=verify, artifacts=artifacts)
        finally:
            self._write_runtime_stats(artifacts, stats_start)

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
        if not report.patchable():
            artifacts.write_unresolved(report)
            return WorkflowResult(
                outcome=WorkflowOutcome.NO_PATCH_NEEDED,
                run_directory=artifacts.run_directory,
                reason="No capability was classified PATCHABLE",
            )

        agent1_feedback: dict[str, Any] | None = None
        limits = project.manifest.limits
        for analysis_round in range(1, limits.agent1_reanalysis_rounds + 1):
            if analysis_round > 1:
                report = analyzer.analyze(project, feedback=agent1_feedback)
                artifacts.write_model("capability-report.json", report)
                if not report.patchable():
                    artifacts.write_unresolved(report)
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
                    if not report.patchable():
                        artifacts.write_text("changes.patch", "")
                        artifacts.write_unresolved(report)
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
                review = reviewer.review(
                    project,
                    report,
                    interface_report,
                    worktree.path,
                    git_diff,
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
                    artifacts.write_unresolved(report)
                    return WorkflowResult(
                        outcome=WorkflowOutcome.PARTIAL,
                        run_directory=artifacts.run_directory,
                        reason="Independent review requires human judgment",
                    )

                if not verify:
                    artifacts.write_unresolved(report)
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
                    artifacts.write_unresolved(report)
                    return WorkflowResult(
                        outcome=WorkflowOutcome.PASS,
                        run_directory=artifacts.run_directory,
                    )
                if verification.route is FailureRoute.AGENT1:
                    agent1_feedback = verification.model_dump(mode="json")
                    requested_reanalysis = True
                    break
                if verification.route is FailureRoute.AGENT2:
                    agent2_feedback = verification.model_dump(mode="json")
                    continue
                artifacts.write_unresolved(report)
                return WorkflowResult(
                    outcome=WorkflowOutcome.PARTIAL,
                    run_directory=artifacts.run_directory,
                    reason=verification.failure_code.value if verification.failure_code else None,
                )

            if requested_reanalysis:
                continue
            artifacts.write_unresolved(report)
            return WorkflowResult(
                outcome=WorkflowOutcome.FAILED,
                run_directory=artifacts.run_directory,
                reason="Agent 2 patch budget exhausted",
            )

        artifacts.write_unresolved(report)
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
                "system_boundary": project.manifest.system_boundary.model_dump(mode="json"),
                "model_profile": self.model_profile,
                "resolved_models": models.model_dump(mode="json"),
                "capability_checks": [
                    check.model_dump(mode="json")
                    for check in project.manifest.capability_checks
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
