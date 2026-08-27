from __future__ import annotations

from pathlib import Path

from consensus_seam.config import LoadedProject
from consensus_seam.languages.base import LanguageBackend
from consensus_seam.models import (
    CommandExecution,
    FailureCode,
    FailureRoute,
    ProjectManifest,
)
from consensus_seam.verify import CapabilityCheck, DeterministicVerifier


class PassingBackend(LanguageBackend):
    def _passed(self, command: str) -> CommandExecution:
        return CommandExecution(command=command, returncode=0, duration_seconds=0)

    def build(self, repo: Path, command: str) -> CommandExecution:
        return self._passed(command)

    def test(self, repo: Path, command: str) -> CommandExecution:
        return self._passed(command)

    def format_changed_files(self, repo: Path) -> CommandExecution:
        return self._passed("format")

    def find_symbol(self, repo: Path, symbol: str) -> list[str]:
        return []

    def find_references(self, repo: Path, symbol: str) -> list[str]:
        return []


def project(tmp_path: Path) -> LoadedProject:
    original = tmp_path / "original"
    original.mkdir()
    manifest = ProjectManifest.model_validate(
        {
            "name": "mini-raft",
            "language": "go",
            "protocol": "raft",
            "repository": str(original),
            "system_boundary": {
                "kind": "protocol_library",
                "description": "Mini Raft protocol core only",
            },
            "build": {"command": "build"},
            "test": {"command": "test"},
        }
    )
    return LoadedProject(
        manifest_path=tmp_path / "project.yaml",
        manifest=manifest,
        repository=original,
        working_directory=original,
        capabilities=None,  # type: ignore[arg-type]
        modification_policy=None,  # type: ignore[arg-type]
        protocol_brief={},
    )


def test_verifier_rejects_unverified_capability_claim(tmp_path: Path) -> None:
    loaded = project(tmp_path)
    patched = tmp_path / "patched"
    patched.mkdir()
    report = DeterministicVerifier(PassingBackend()).verify(
        loaded,
        patched,
        required_capabilities={"message_injection"},
    )
    assert report.passed is False
    assert report.failure_code is FailureCode.SEMANTIC_AMBIGUITY
    assert report.route is FailureRoute.NEEDS_HUMAN


def test_message_capture_requires_capture_and_suppression_checks(tmp_path: Path) -> None:
    loaded = project(tmp_path)
    patched = tmp_path / "patched"
    patched.mkdir()
    report = DeterministicVerifier(PassingBackend()).verify(
        loaded,
        patched,
        capability_checks=[
            CapabilityCheck(
                name="MC1",
                capability="message_capture",
                command="mc1",
                failure_code=FailureCode.MESSAGE_CAPTURE_FAILED,
            )
        ],
        required_capabilities={"message_capture"},
    )
    assert report.passed is False
    assert "MESSAGE_SUPPRESSION_FAILED" in report.details[0]


def test_registered_capability_check_is_executed(tmp_path: Path) -> None:
    loaded = project(tmp_path)
    patched = tmp_path / "patched"
    patched.mkdir()
    report = DeterministicVerifier(PassingBackend()).verify(
        loaded,
        patched,
        capability_checks=[
            CapabilityCheck(
                name="MC3",
                capability="message_injection",
                command="mc3",
                failure_code=FailureCode.MESSAGE_INJECTION_FAILED,
            )
        ],
        required_capabilities={"message_injection"},
    )
    assert report.passed is True
    assert [execution.command for execution in report.capability_tests] == ["mc3"]
