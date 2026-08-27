"""Baseline build and test execution against the untouched repository."""

from __future__ import annotations

from ..config import LoadedProject
from ..languages.base import LanguageBackend
from ..models import BaselineReport, FailureCode


class BaselineVerifier:
    def __init__(self, backend: LanguageBackend) -> None:
        self.backend = backend

    def run(self, project: LoadedProject) -> BaselineReport:
        build = self.backend.build(
            project.working_directory,
            project.manifest.build.command,
        )
        if not build.passed:
            return BaselineReport(
                passed=False,
                build=build,
                failure_code=FailureCode.BASELINE_FAILED,
            )
        tests = self.backend.test(
            project.working_directory,
            project.manifest.test.command,
        )
        return BaselineReport(
            passed=tests.passed,
            build=build,
            tests=tests,
            failure_code=None if tests.passed else FailureCode.BASELINE_FAILED,
        )
