"""在未修改目标仓库上执行 baseline 构建和测试。"""

from __future__ import annotations

from ..config import LoadedProject
from ..languages.base import LanguageBackend
from ..models import BaselineReport, FailureCode


class BaselineVerifier:
    """在未修改目标仓库上执行构建和原始测试。"""

    def __init__(self, backend: LanguageBackend) -> None:
        self.backend = backend

    def run(self, project: LoadedProject) -> BaselineReport:
        """先构建后测试；任一步失败都标记 BASELINE_FAILED。"""

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
