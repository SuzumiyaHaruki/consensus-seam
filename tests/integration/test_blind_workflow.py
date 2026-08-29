from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from consensus_seam.config import load_project
from consensus_seam.llm.base import ToolExecutor
from consensus_seam.models import AgentModelConfig, WorkflowOutcome
from consensus_seam.workflow import ConsensusWorkflow
from tests.helpers import capability_report, review_report


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class BlindFakeRuntime:
    reviewer_saw_hidden_fixture = False

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
        *,
        agent: str,
        model: AgentModelConfig,
        tools: ToolExecutor | None = None,
        invocation_id: str | None = None,
    ) -> str:
        if agent == "analyzer":
            report = capability_report()
            report["target"] = "blind-mini"
            return json.dumps(report)
        if agent == "transformer":
            assert tools is not None
            result = json.loads(
                tools.execute(
                    "write_file",
                    json.dumps(
                        {
                            "path": "hidden_api.go",
                            "content": "package mini\n\nfunc HiddenValue() int { return 42 }\n",
                        }
                    ),
                )
            )
            assert result["ok"] is True
            return json.dumps(
                {
                    "message_injection": {
                        "implemented": True,
                        "entrypoint": {"symbol": "HiddenValue"},
                    }
                }
            )
        assert tools is not None
        listing = json.loads(
            tools.execute(
                "list_files",
                json.dumps({"scope": "patched", "path": "."}),
            )
        )
        self.reviewer_saw_hidden_fixture = any(
            "_consensus_seam_hidden" in path
            for path in listing["result"]["files"]
        )
        return json.dumps(review_report())


def test_hidden_acceptance_is_materialized_only_for_verifier(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("GOCACHE", str(tmp_path / "gocache"))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "go.mod").write_text("module example.invalid/mini\n\ngo 1.22\n")
    (repo / "node.go").write_text("package mini\n")
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

    hidden = tmp_path / "hidden_test.go"
    hidden.write_text(
        """package acceptance_test

import (
    "testing"
    mini "example.invalid/mini"
)

func TestHidden(t *testing.T) {
    if mini.HiddenValue() != 42 { t.Fatal("hidden API failed") }
}
""",
        encoding="utf-8",
    )
    manifest = tmp_path / "project.yaml"
    manifest.write_text(
        "\n".join(
            [
                "name: blind-mini",
                "language: go",
                "protocol: raft",
                f"repository: {repo}",
                "system_boundary:",
                "  kind: protocol_library",
                "  description: blind fixture test",
                "transform_capabilities: [message_injection]",
                "build: {command: 'go test -run=^$ ./...'}",
                "test: {command: 'go test ./...'}",
                "capability_checks:",
                "  - name: hidden injection check",
                "    capability: message_injection",
                "    command: go test ./_consensus_seam_hidden/acceptance",
                "    failure_code: MESSAGE_INJECTION_FAILED",
                "  - name: hidden failed-delivery retention check",
                "    capability: message_injection",
                "    command: go test ./_consensus_seam_hidden/acceptance",
                "    failure_code: MESSAGE_INJECTION_RETENTION_FAILED",
                "verification_fixtures:",
                f"  - source: {hidden}",
                "    destination: _consensus_seam_hidden/acceptance/hidden_test.go",
            ]
        ),
        encoding="utf-8",
    )

    runtime = BlindFakeRuntime()
    workflow = ConsensusWorkflow(
        runtime,
        runs_root=tmp_path / "runs",
        controller_repository=repo,
    )
    result = workflow.run(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PASS
    assert runtime.reviewer_saw_hidden_fixture is False
    assert not (
        result.run_directory
        / "patched-worktree/_consensus_seam_hidden/acceptance/hidden_test.go"
    ).exists()
    patch = (result.run_directory / "changes.patch").read_text()
    assert "hidden_api.go" in patch
    assert "hidden_test.go" not in patch
    metrics = json.loads((result.run_directory / "patch-metrics.json").read_text())
    assert metrics["new_production_files"] == ["hidden_api.go"]
