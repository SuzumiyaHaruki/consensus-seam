"""Build, regression, and explicit capability-test execution."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..config import LoadedProject
from ..languages.base import LanguageBackend
from ..models import FailureCode, FailureRoute, VerificationReport
from ..routing import route_failure
from .capability import CapabilityCheck


class DeterministicVerifier:
    def __init__(self, backend: LanguageBackend) -> None:
        self.backend = backend

    def verify(
        self,
        project: LoadedProject,
        patched_worktree: Path,
        *,
        capability_checks: Iterable[CapabilityCheck] = (),
    ) -> VerificationReport:
        relative_working_directory = project.working_directory.relative_to(project.repository)
        working_directory = patched_worktree / relative_working_directory

        build = self.backend.build(working_directory, project.manifest.build.command)
        if not build.passed:
            code = FailureCode.BUILD_FAILED
            return VerificationReport(
                passed=False,
                build=build,
                failure_code=code,
                route=route_failure(code),
            )

        existing_tests = self.backend.test(working_directory, project.manifest.test.command)
        if not existing_tests.passed:
            code = FailureCode.REGRESSION_FAILED
            return VerificationReport(
                passed=False,
                build=build,
                existing_tests=existing_tests,
                failure_code=code,
                route=route_failure(code),
            )

        executions = []
        for check in capability_checks:
            execution = self.backend.test(working_directory, check.command)
            executions.append(execution)
            if not execution.passed:
                return VerificationReport(
                    passed=False,
                    build=build,
                    existing_tests=existing_tests,
                    capability_tests=executions,
                    failure_code=check.failure_code,
                    route=route_failure(check.failure_code),
                    details=[f"capability check failed: {check.name}"],
                )

        return VerificationReport(
            passed=True,
            build=build,
            existing_tests=existing_tests,
            capability_tests=executions,
            details=(
                []
                if executions
                else [
                    "No separately configured capability checks; the target test command "
                    "is expected to include generated target-language tests."
                ]
            ),
        )
