from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from consensus_seam.cli import main
from consensus_seam.config import load_project
from consensus_seam.llm.client import FakeLLMClient
from consensus_seam.llm.runtime import ToolCallingAgentRuntime
from consensus_seam.models import WorkflowOutcome
from consensus_seam.models import AgentModelConfig
from consensus_seam.llm.base import ToolExecutor
from consensus_seam.workflow import ConsensusWorkflow, ExperimentPreconditionError
from tests.helpers import capability_report, review_report, write_project_manifest


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
        agent: str,
        model: AgentModelConfig,
        tools: ToolExecutor | None = None,
        invocation_id: str | None = None,
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
                        "message_id_scope": "test_session",
                        "controller_operations": "serialized",
                        "entrypoint": {
                            "file": "injection_seam.go",
                            "symbol": "injectForTest",
                            "meaning": "test-only wrapper around the normal handler",
                        },
                        "notes": ["test fixture change"],
                    }
                }
            )
        return json.dumps(review_report())


class GuardrailFakeRuntime:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.transformer_round = 0

    @staticmethod
    def _write(tools: ToolExecutor | None, path: str, content: str) -> None:
        assert tools is not None
        result = json.loads(
            tools.execute("write_file", json.dumps({"path": path, "content": content}))
        )
        assert result["ok"] is True

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
            if self.mode == "rediscovered":
                report["capabilities"]["message_capture"]["status"] = "PATCHABLE"
            return json.dumps(report)
        if agent == "reviewer":
            return json.dumps(review_report())

        self.transformer_round += 1
        payload = json.loads(user_prompt)
        if self.mode == "protected_test" and self.transformer_round == 1:
            self._write(tools, "node_test.go", "package mini\n\n// weakened\n")
            return json.dumps(
                {
                    "message_injection": {
                        "implemented": True,
                        "message_id_scope": "test_session",
                        "controller_operations": "serialized",
                        "entrypoint": {"symbol": "injectForTest"},
                    }
                }
            )
        if self.mode == "rediscovered" and self.transformer_round == 1:
            self._write(
                tools,
                "capture_seam.go",
                "package mini\n\nfunc contaminatedCaptureChange() {}\n",
            )
            return json.dumps(
                {
                    "message_capture": {
                        "implemented": False,
                        "rediscovered_status": "INVASIVE_REDISCOVERED",
                    },
                    "message_injection": {
                        "implemented": True,
                        "message_id_scope": "test_session",
                        "controller_operations": "serialized",
                        "entrypoint": {"symbol": "injectForTest"},
                    },
                }
            )

        expected_failure = (
            "EXISTING_TEST_MODIFIED"
            if self.mode == "protected_test"
            else "INVASIVE_REDISCOVERED"
        )
        assert payload["feedback"]["failure"] == expected_failure
        self._write(
            tools,
            "injection_seam.go",
            "package mini\n\nfunc injectForTest() {}\n",
        )
        return json.dumps(
            {
                "message_injection": {
                    "implemented": True,
                    "message_id_scope": "test_session",
                    "controller_operations": "serialized",
                    "entrypoint": {
                        "file": "injection_seam.go",
                        "symbol": "injectForTest",
                    },
                }
            }
        )


class AnalyzerChatClient:
    def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(capability_report()),
                    },
                }
            ],
        }


class ScopedTransformRuntime:
    def __init__(self) -> None:
        self.transform_payload: dict[str, Any] | None = None

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
            report["capabilities"]["randomness_control"] = {
                "status": "PATCHABLE",
                "evidence": [
                    {
                        "symbol": "NewNode",
                        "reason": "random source is constructed internally",
                    }
                ],
                "gap": "random source is not injectable",
            }
            return json.dumps(report)
        if agent == "transformer":
            self.transform_payload = json.loads(user_prompt)
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
                        "message_id_scope": "test_session",
                        "controller_operations": "serialized",
                        "entrypoint": {"symbol": "injectForTest"},
                    }
                }
            )
        return json.dumps(review_report())


def test_analyze_writes_validated_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = write_project_manifest(tmp_path, repo)
    workflow = ConsensusWorkflow(
        FakeLLMClient([json.dumps(capability_report())]),
        runs_root=tmp_path / "runs",
    )
    result = workflow.analyze(load_project(manifest))
    assert result.outcome is WorkflowOutcome.ANALYZED
    assert (result.run_directory / "capability-report.json").is_file()
    assert (result.run_directory / "unresolved.json").is_file()
    assert json.loads((result.run_directory / "agent-run-stats.json").read_text()) == []


def test_live_runtime_stats_are_written_without_reasoning_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = write_project_manifest(tmp_path, repo)
    workflow = ConsensusWorkflow(
        ToolCallingAgentRuntime(AnalyzerChatClient()),
        runs_root=tmp_path / "runs",
    )
    result = workflow.analyze(load_project(manifest))
    stats = json.loads((result.run_directory / "agent-run-stats.json").read_text())
    assert stats[0]["agent"] == "analyzer"
    assert stats[0]["invocation_id"] == "analyzer-a1-attempt1"
    assert stats[0]["input_tokens"] == 100
    assert stats[0]["output_tokens"] == 20
    assert "reasoning_content" not in stats[0]


def test_patch_stops_when_analysis_finds_no_patchable_capability(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = write_project_manifest(tmp_path, repo)
    workflow = ConsensusWorkflow(
        FakeLLMClient([json.dumps(capability_report(patchable=None))]),
        runs_root=tmp_path / "runs",
    )
    result = workflow.patch(load_project(manifest))
    assert result.outcome is WorkflowOutcome.NO_PATCH_NEEDED
    assert not (result.run_directory / "patched-worktree").exists()


def test_transform_scope_does_not_hide_unselected_patchable_findings(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(
        tmp_path,
        repo,
        command="git diff --check",
        extra=("transform_capabilities:", "  - message_injection"),
    )
    runtime = ScopedTransformRuntime()
    workflow = ConsensusWorkflow(runtime, runs_root=tmp_path / "runs")
    result = workflow.patch(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PASS
    assert runtime.transform_payload is not None
    assert runtime.transform_payload["patchable_capabilities"] == [
        "message_injection"
    ]
    report = json.loads((result.run_directory / "capability-report.json").read_text())
    assert report["capabilities"]["randomness_control"]["status"] == "PATCHABLE"
    unresolved = json.loads((result.run_directory / "unresolved.json").read_text())
    assert unresolved["randomness_control"] == {
        "reason": "outside this run's transform_capabilities scope",
        "status": "PATCHABLE",
    }
    run_config = json.loads((result.run_directory / "run-config.json").read_text())
    assert run_config["transform_capabilities"] == ["message_injection"]


def test_patch_runs_isolated_three_agent_flow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(tmp_path, repo, command="git diff --check")
    workflow = ConsensusWorkflow(EditingFakeClient(), runs_root=tmp_path / "runs")
    result = workflow.patch(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PASS
    assert "injection_seam.go" in (result.run_directory / "changes.patch").read_text()
    assert not (repo / "injection_seam.go").exists()


def test_run_includes_baseline_and_deterministic_verification(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(
        tmp_path,
        repo,
        command="git diff --check",
        extra=(
            "capability_checks:",
            "  - name: MC3 exact injection",
            "    capability: message_injection",
            "    command: git diff --check",
            "    failure_code: MESSAGE_INJECTION_FAILED",
        ),
    )
    workflow = ConsensusWorkflow(EditingFakeClient(), runs_root=tmp_path / "runs")
    result = workflow.run(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PASS
    assert (result.run_directory / "baseline-report.json").is_file()
    assert (result.run_directory / "verification-report.json").is_file()
    assert (result.run_directory / "patch-metrics.json").is_file()
    assert (result.run_directory / "tool-call-audit.json").is_file()
    run_config = json.loads((result.run_directory / "run-config.json").read_text())
    assert run_config["resolved_models"]["reviewer"]["model"] == "deepseek-v4-pro"
    assert run_config["source_revisions"]["target"]["revision"] is not None
    assert run_config["source_revisions"]["target"]["dirty"] is False
    assert (tmp_path / "runs/latest/verification-report.json").is_file()
    assert not (tmp_path / "runs/latest/patched-worktree").exists()


def test_run_refuses_success_without_capability_check(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(tmp_path, repo, command="git diff --check")
    workflow = ConsensusWorkflow(EditingFakeClient(), runs_root=tmp_path / "runs")
    result = workflow.run(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PARTIAL
    assert result.reason == "SEMANTIC_AMBIGUITY"
    verification = json.loads(
        (result.run_directory / "verification-report.json").read_text()
    )
    assert "MESSAGE_INJECTION_FAILED" in verification["details"][0]


def test_existing_go_tests_are_protected_and_bad_worktree_is_discarded(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    original_test = "package mini\n\nfunc TestExisting(t *testing.T) {}\n"
    (repo / "node_test.go").write_text(original_test, encoding="utf-8")
    git(repo, "add", "node_test.go")
    git(
        repo,
        "-c",
        "user.name=ConsensusSeam Test",
        "-c",
        "user.email=consensus-seam@example.invalid",
        "commit",
        "-m",
        "add existing test",
    )
    manifest = write_project_manifest(tmp_path, repo, command="git diff --check")
    workflow = ConsensusWorkflow(
        GuardrailFakeRuntime("protected_test"), runs_root=tmp_path / "runs"
    )
    result = workflow.patch(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PASS
    assert (result.run_directory / "logs/protected-files-a1-p1.json").is_file()
    patch = (result.run_directory / "changes.patch").read_text(encoding="utf-8")
    assert "injection_seam.go" in patch
    assert "node_test.go" not in patch
    assert (repo / "node_test.go").read_text(encoding="utf-8") == original_test


def test_rediscovered_invasive_change_always_uses_fresh_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(tmp_path, repo, command="git diff --check")
    workflow = ConsensusWorkflow(
        GuardrailFakeRuntime("rediscovered"), runs_root=tmp_path / "runs"
    )
    result = workflow.patch(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PASS
    assert (result.run_directory / "logs/discarded-a1-p1.json").is_file()
    patch = (result.run_directory / "changes.patch").read_text(encoding="utf-8")
    assert "injection_seam.go" in patch
    assert "capture_seam.go" not in patch
    assert (result.run_directory / "patched-worktree/capture_seam.go").is_file()
    assert not (
        result.run_directory / "patched-worktree-a1-p2/capture_seam.go"
    ).exists()


def test_cli_analyze_command(tmp_path: Path, capsys: Any) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = write_project_manifest(tmp_path, repo)
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


@pytest.mark.parametrize("dirty_repository", ["controller", "target"])
def test_formal_experiment_requires_clean_revisions(
    tmp_path: Path,
    dirty_repository: str,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    initialize_git_repository(target)
    controller = tmp_path / "controller"
    controller.mkdir()
    initialize_git_repository(controller)
    dirty = controller if dirty_repository == "controller" else target
    (dirty / "node.go").write_text("package mini\n\n// dirty\n", encoding="utf-8")
    manifest = write_project_manifest(
        tmp_path,
        target,
        extra=(
            "experiment:",
            "  kind: blind_capability",
            "  oracle_visible_to_agents: false",
            "  research_claim: clean revision guard",
        ),
    )
    workflow = ConsensusWorkflow(
        FakeLLMClient([json.dumps(capability_report())]),
        runs_root=tmp_path / "runs",
        controller_repository=controller,
    )
    with pytest.raises(ExperimentPreconditionError, match=dirty_repository):
        workflow.analyze(load_project(manifest))
    assert not (tmp_path / "runs").exists()
