from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from consensus_seam.cli import main
from consensus_seam.config import load_project
from consensus_seam.llm.client import FakeLLMClient
from consensus_seam.models import WorkflowOutcome
from consensus_seam.models import AgentModelConfig
from consensus_seam.llm.base import ToolExecutor
from consensus_seam.workflow import ConsensusWorkflow
from tests.helpers import capability_report


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def initialize_git_repository(repo: Path) -> None:
    git(repo, "init")
    (repo / "go.mod").write_text("module example.invalid/mini\n\ngo 1.22\n", encoding="utf-8")
    (repo / "node.go").write_text("package mini\n", encoding="utf-8")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=ConsensusSeam Test",
        "-c",
        "user.email=consensus-seam@example.invalid",
        "commit",
        "-m",
        "initial",
    )


class EditingFakeClient:
    """A test-only stand-in for a future tool-capable coding Agent adapter."""

    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
        *,
        model: AgentModelConfig,
        tools: ToolExecutor | None = None,
    ) -> str:
        self.calls += 1
        if self.calls == 1:
            return json.dumps(capability_report())
        if self.calls == 2:
            assert tools is not None
            result = json.loads(
                tools.execute(
                    "write_file",
                    json.dumps(
                        {
                            "path": "injection_seam.go",
                            "content": "package mini\n\nfunc injectForTest() {}\n",
                        }
                    ),
                )
            )
            assert result["ok"] is True
            return json.dumps(
                {
                    "message_injection": {
                        "implemented": True,
                        "entrypoint": {
                            "file": "injection_seam.go",
                            "symbol": "injectForTest",
                            "meaning": "test-only wrapper around the normal handler",
                        },
                        "notes": ["test fixture change"],
                    }
                }
            )
        return json.dumps({"overall": "PASS", "issues": []})


def test_analyze_writes_validated_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = tmp_path / "project.yaml"
    manifest.write_text(
        "\n".join(
            [
                "name: mini-raft",
                "language: go",
                "protocol: raft",
                f"repository: {repo}",
                "system_boundary:",
                "  kind: protocol_library",
                "  description: Mini Raft protocol core only",
                "build:",
                "  command: go test ./...",
                "test:",
                "  command: go test ./...",
            ]
        ),
        encoding="utf-8",
    )
    workflow = ConsensusWorkflow(
        FakeLLMClient([json.dumps(capability_report())]),
        runs_root=tmp_path / "runs",
    )
    result = workflow.analyze(load_project(manifest))
    assert result.outcome is WorkflowOutcome.ANALYZED
    assert (result.run_directory / "capability-report.json").is_file()
    assert (result.run_directory / "unresolved.json").is_file()


def test_patch_stops_when_analysis_finds_no_patchable_capability(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = tmp_path / "project.yaml"
    manifest.write_text(
        "\n".join(
            [
                "name: mini-raft",
                "language: go",
                "protocol: raft",
                f"repository: {repo}",
                "system_boundary:",
                "  kind: protocol_library",
                "  description: Mini Raft protocol core only",
                "build: {command: 'go test ./...'}",
                "test: {command: 'go test ./...'}",
            ]
        ),
        encoding="utf-8",
    )
    workflow = ConsensusWorkflow(
        FakeLLMClient([json.dumps(capability_report(patchable=None))]),
        runs_root=tmp_path / "runs",
    )
    result = workflow.patch(load_project(manifest))
    assert result.outcome is WorkflowOutcome.NO_PATCH_NEEDED
    assert not (result.run_directory / "patched-worktree").exists()


def test_patch_runs_isolated_three_agent_flow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = tmp_path / "project.yaml"
    manifest.write_text(
        "\n".join(
            [
                "name: mini-raft",
                "language: go",
                "protocol: raft",
                f"repository: {repo}",
                "system_boundary:",
                "  kind: protocol_library",
                "  description: Mini Raft protocol core only",
                "build: {command: 'git diff --check'}",
                "test: {command: 'git diff --check'}",
            ]
        ),
        encoding="utf-8",
    )
    workflow = ConsensusWorkflow(EditingFakeClient(), runs_root=tmp_path / "runs")
    result = workflow.patch(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PASS
    assert "injection_seam.go" in (result.run_directory / "changes.patch").read_text()
    assert not (repo / "injection_seam.go").exists()


def test_run_includes_baseline_and_deterministic_verification(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = tmp_path / "project.yaml"
    manifest.write_text(
        "\n".join(
            [
                "name: mini-raft",
                "language: go",
                "protocol: raft",
                f"repository: {repo}",
                "system_boundary:",
                "  kind: protocol_library",
                "  description: Mini Raft protocol core only",
                "build: {command: 'git diff --check'}",
                "test: {command: 'git diff --check'}",
                "capability_checks:",
                "  - name: MC3 exact injection",
                "    capability: message_injection",
                "    command: git diff --check",
                "    failure_code: MESSAGE_INJECTION_FAILED",
            ]
        ),
        encoding="utf-8",
    )
    workflow = ConsensusWorkflow(EditingFakeClient(), runs_root=tmp_path / "runs")
    result = workflow.run(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PASS
    assert (result.run_directory / "baseline-report.json").is_file()
    assert (result.run_directory / "verification-report.json").is_file()
    run_config = json.loads((result.run_directory / "run-config.json").read_text())
    assert run_config["resolved_models"]["reviewer"]["model"] == "deepseek-v4-pro"


def test_run_refuses_success_without_capability_check(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = tmp_path / "project.yaml"
    manifest.write_text(
        "\n".join(
            [
                "name: mini-raft",
                "language: go",
                "protocol: raft",
                f"repository: {repo}",
                "system_boundary:",
                "  kind: protocol_library",
                "  description: Mini Raft protocol core only",
                "build: {command: 'git diff --check'}",
                "test: {command: 'git diff --check'}",
            ]
        ),
        encoding="utf-8",
    )
    workflow = ConsensusWorkflow(EditingFakeClient(), runs_root=tmp_path / "runs")
    result = workflow.run(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PARTIAL
    assert result.reason == "SEMANTIC_AMBIGUITY"
    verification = json.loads(
        (result.run_directory / "verification-report.json").read_text()
    )
    assert "MESSAGE_INJECTION_FAILED" in verification["details"][0]


def test_cli_analyze_command(tmp_path: Path, capsys: Any) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = tmp_path / "project.yaml"
    manifest.write_text(
        "\n".join(
            [
                "name: mini-raft",
                "language: go",
                "protocol: raft",
                f"repository: {repo}",
                "system_boundary:",
                "  kind: protocol_library",
                "  description: Mini Raft protocol core only",
                "build: {command: 'go test ./...'}",
                "test: {command: 'go test ./...'}",
            ]
        ),
        encoding="utf-8",
    )
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps([capability_report()]), encoding="utf-8")
    exit_code = main(
        [
            "analyze",
            "--project",
            str(manifest),
            "--responses",
            str(responses),
            "--runs-root",
            str(tmp_path / "cli-runs"),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["outcome"] == "ANALYZED"
