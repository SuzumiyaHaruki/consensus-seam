from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from consensus_seam.cli import main
from consensus_seam.config import load_posthoc_checks, load_project
from consensus_seam.llm.client import FakeLLMClient
from consensus_seam.llm.runtime import ToolCallingAgentRuntime
from consensus_seam.models import WorkflowOutcome
from consensus_seam.models import AgentModelConfig
from consensus_seam.llm.base import AgentRuntimeError, ToolExecutor
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


class PostHocSourceRuntime:
    """生成一个可编译但尚未满足后置真实测试的候选接口。"""

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
            return json.dumps(capability_report())
        if agent == "transformer":
            assert tools is not None
            result = json.loads(
                tools.execute(
                    "write_file",
                    json.dumps(
                        {
                            "path": "generated.go",
                            "content": "package mini\n\nfunc GeneratedValue() int { return 1 }\n",
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
                        "entrypoint": {
                            "file": "generated.go",
                            "symbol": "GeneratedValue",
                        },
                        "implementation_approach": ["test accessor"],
                    }
                }
            )
        return json.dumps(review_report())


class PostHocRepairRuntime:
    """只执行 Agent 2 修复与 Agent 3 复审，不允许重新分析。"""

    def __init__(self) -> None:
        self.agents: list[str] = []

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
        self.agents.append(agent)
        if agent == "analyzer":
            raise AssertionError("repair must not rerun Analyzer")
        if agent == "transformer":
            payload = json.loads(user_prompt)
            assert payload["feedback"]["failure"] == "POST_HOC_VERIFICATION_FAILED"
            assert tools is not None
            result = json.loads(
                tools.execute(
                    "apply_patch",
                    json.dumps(
                        {
                            "patch": """diff --git a/generated.go b/generated.go
--- a/generated.go
+++ b/generated.go
@@ -3 +3 @@
-func GeneratedValue() int { return 1 }
+func GeneratedValue() int { return 2 }
"""
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
                        "entrypoint": {
                            "file": "generated.go",
                            "symbol": "GeneratedValue",
                        },
                        "implementation_approach": ["post-hoc repair"],
                    }
                }
            )
        return json.dumps(review_report())


class SplitCapabilityRuntime:
    """确认消息捕获与注入共享一个 Transformer 工具循环。"""

    def __init__(self) -> None:
        self.transform_calls: list[list[str]] = []

    def analyzer_report(self) -> dict[str, Any]:
        report = capability_report()
        report["capabilities"]["message_capture"].update(
            {
                "status": "PATCHABLE",
                "gap": "capture facade missing",
                "existing_test_interface_complete": False,
                "test_support_reason": "output is not retained",
                "suggested_changes": ["add a cache facade"],
            }
        )
        return report

    def review_response(self) -> dict[str, Any]:
        return review_report()

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
            return json.dumps(self.analyzer_report())
        if agent == "transformer":
            selected = json.loads(user_prompt)["patchable_capabilities"]
            self.transform_calls.append(selected)
            assert tools is not None
            for capability in selected:
                result = json.loads(
                    tools.execute(
                        "write_file",
                        json.dumps(
                            {
                                "path": f"generated_{capability}.go",
                                "content": f"package mini\n\n// {capability}\n",
                            }
                        ),
                    )
                )
                assert result["ok"] is True
            return json.dumps(
                {
                    capability: {
                        "implemented": True,
                        "implementation_approach": ["target-native seam"],
                    }
                    for capability in selected
                }
            )
        return json.dumps(self.review_response())


class SelectiveReviewerRevisionRuntime(SplitCapabilityRuntime):
    """Reviewer 只指出消息问题时，下一轮不应重跑其他有效能力。"""

    def __init__(self) -> None:
        super().__init__()
        self.review_round = 0

    def analyzer_report(self) -> dict[str, Any]:
        report = super().analyzer_report()
        report["capabilities"]["randomness_control"] = {
            "status": "PATCHABLE",
            "evidence": [
                {
                    "symbol": "RandomSource",
                    "reason": "random source cannot be fixed by tests",
                }
            ],
            "gap": "no deterministic random source",
            "existing_test_interface_complete": False,
            "test_support_reason": "randomness needs a configuration hook",
            "suggested_changes": ["add a validated test configuration"],
        }
        return report

    def review_response(self) -> dict[str, Any]:
        self.review_round += 1
        review = review_report()
        if self.review_round == 1:
            review["overall"] = "REVISE_AGENT2"
            review["issues"] = [
                {
                    "capability": "message_capture",
                    "reason": "capture snapshot is not isolated",
                }
            ]
        return review


class ReviewerRevisionRuntime:
    """Reviewer 阻塞问题应在下一 fresh worktree 中修订既有候选。"""

    def __init__(self) -> None:
        self.transform_round = 0
        self.review_round = 0
        self.saw_prior_candidate = False

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
            return json.dumps(capability_report())
        if agent == "transformer":
            self.transform_round += 1
            assert tools is not None
            payload = json.loads(user_prompt)
            if self.transform_round == 1:
                content = "package mini\n\nfunc InjectVersion() int { return 1 }\n"
            else:
                assert payload["feedback"]["failure"] == "REVIEW_REVISE_AGENT2"
                read = json.loads(
                    tools.execute(
                        "read_file",
                        json.dumps(
                            {
                                "scope": "worktree",
                                "path": "injection_seam.go",
                                "start": 1,
                                "end": 20,
                            }
                        ),
                    )
                )
                self.saw_prior_candidate = "return 1" in "\n".join(
                    read["result"]["lines"]
                )
                content = "package mini\n\nfunc InjectVersion() int { return 2 }\n"
            written = json.loads(
                tools.execute(
                    "write_file",
                    json.dumps({"path": "injection_seam.go", "content": content}),
                )
            )
            assert written["ok"] is True
            return json.dumps(
                {
                    "message_injection": {
                        "implemented": True,
                        "message_id_scope": "test_session",
                        "entrypoint": {
                            "file": "injection_seam.go",
                            "symbol": "InjectVersion",
                        },
                        "implementation_approach": ["target-native test seam"],
                    }
                }
            )

        self.review_round += 1
        review = review_report()
        if self.review_round == 1:
            review["overall"] = "REVISE_AGENT2"
            for check in review["checks"]:
                if check["name"] == "testing_contract_conformance":
                    check["result"] = "FAIL"
            review["issues"] = [
                {
                    "capability": "message_injection",
                    "file": "injection_seam.go",
                    "symbol": "InjectVersion",
                    "reason": "The first candidate needs an implementation revision.",
                }
            ]
        return json.dumps(review)


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
                capture = report["capabilities"]["message_capture"]
                capture["status"] = "PATCHABLE"
                capture["existing_test_interface_complete"] = False
                capture["test_support_reason"] = "capture still needs test support"
                capture["suggested_changes"] = ["add a capture hook"]
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
                        "implementation_approach": [
                            "joint message-control candidate discarded with capture"
                        ],
                    }
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
                "existing_test_interface_complete": False,
                "test_support_reason": "random source is not directly controllable",
                "suggested_changes": ["inject the existing random source"],
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
        "reason": "不在本次 transform_capabilities 实验范围内",
        "status": "PATCHABLE",
    }
    run_config = json.loads((result.run_directory / "run-config.json").read_text())
    assert run_config["transform_capabilities"] == ["message_injection"]


def test_patch_groups_capture_and_injection_into_one_transform_call(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(tmp_path, repo, command="git diff --check")
    runtime = SplitCapabilityRuntime()

    result = ConsensusWorkflow(runtime, runs_root=tmp_path / "runs").patch(
        load_project(manifest)
    )

    assert result.outcome is WorkflowOutcome.PASS
    assert runtime.transform_calls == [["message_capture", "message_injection"]]
    interface = json.loads(
        (result.run_directory / "interface-report.json").read_text(encoding="utf-8")
    )
    assert interface["message_capture"]["implemented"] is True
    assert interface["message_injection"]["implemented"] is True


def test_reviewer_revision_only_reruns_implicated_capability_group(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(tmp_path, repo, command="git diff --check")
    runtime = SelectiveReviewerRevisionRuntime()

    result = ConsensusWorkflow(runtime, runs_root=tmp_path / "runs").patch(
        load_project(manifest)
    )

    assert result.outcome is WorkflowOutcome.PASS
    assert runtime.transform_calls == [
        ["message_capture", "message_injection"],
        ["randomness_control"],
        ["message_capture", "message_injection"],
    ]
    interface = json.loads(
        (result.run_directory / "interface-report.json").read_text(encoding="utf-8")
    )
    assert interface["randomness_control"]["implemented"] is True


def test_reviewer_revision_continues_from_prior_candidate_in_fresh_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(tmp_path, repo, command="git diff --check")
    runtime = ReviewerRevisionRuntime()

    result = ConsensusWorkflow(runtime, runs_root=tmp_path / "runs").patch(
        load_project(manifest)
    )

    assert result.outcome is WorkflowOutcome.PASS
    assert runtime.transform_round == 2
    assert runtime.review_round == 2
    assert runtime.saw_prior_candidate is True
    first = result.run_directory / "patched-worktree/injection_seam.go"
    revised = result.run_directory / "patched-worktree-a1-p2/injection_seam.go"
    assert "return 1" in first.read_text(encoding="utf-8")
    assert "return 2" in revised.read_text(encoding="utf-8")
    usage = (result.run_directory / "USAGE.md").read_text(encoding="utf-8")
    assert "总体结论：`PASS`" in usage


def test_patch_runs_isolated_three_agent_flow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(tmp_path, repo, command="git diff --check")
    workflow = ConsensusWorkflow(EditingFakeClient(), runs_root=tmp_path / "runs")
    result = workflow.patch(load_project(manifest))
    assert result.outcome is WorkflowOutcome.PASS
    assert "injection_seam.go" in (result.run_directory / "changes.patch").read_text()
    usage = (result.run_directory / "USAGE.md").read_text(encoding="utf-8")
    assert "测试接口清单" in usage
    assert "injectForTest" in usage
    assert (result.run_directory / "AUDIT.md").is_file()
    assert not (repo / "injection_seam.go").exists()


def test_posthoc_repair_reuses_candidate_and_routes_failure_to_agent2(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("GOCACHE", str(tmp_path / "gocache"))
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_git_repository(repo)
    manifest = write_project_manifest(tmp_path, repo, command="go test ./...")
    project = load_project(manifest)

    source_result = ConsensusWorkflow(
        PostHocSourceRuntime(),
        runs_root=tmp_path / "source-runs",
    ).patch(project)
    assert source_result.outcome is WorkflowOutcome.PASS

    fixture = tmp_path / "generated_interface_test.go"
    fixture.write_text(
        """package acceptance_test

import (
    "testing"
    mini "example.invalid/mini"
)

func TestGeneratedInterface(t *testing.T) {
    if got := mini.GeneratedValue(); got != 2 {
        t.Fatalf("GeneratedValue() = %d, want 2", got)
    }
}
""",
        encoding="utf-8",
    )
    checks_path = tmp_path / "post-hoc-checks.yaml"
    checks_path.write_text(
        "\n".join(
            [
                "capability_checks:",
                "  - name: generated interface scenario",
                "    capability: message_injection",
                "    command: go test ./_consensus_seam_posthoc/acceptance -run '^TestGeneratedInterface$' -count=1",
                "    failure_code: MESSAGE_INJECTION_FAILED",
                "verification_fixtures:",
                f"  - source: {fixture.name}",
                "    destination: _consensus_seam_posthoc/acceptance/generated_interface_test.go",
            ]
        ),
        encoding="utf-8",
    )
    checks = load_posthoc_checks(checks_path, repository=repo)
    runtime = PostHocRepairRuntime()

    result = ConsensusWorkflow(
        runtime,
        runs_root=tmp_path / "repair-runs",
    ).repair(
        project,
        source_run=source_result.run_directory,
        checks=checks,
    )

    assert result.outcome is WorkflowOutcome.REPAIRED
    assert runtime.agents == ["transformer", "reviewer"]
    patch = (result.run_directory / "changes.patch").read_text(encoding="utf-8")
    assert "return 2" in patch
    assert not (repo / "generated.go").exists()
    assert (result.run_directory / "logs/verification-initial.json").is_file()
    assert (result.run_directory / "logs/verification-repair-p1.json").is_file()
    assert not (
        result.run_directory
        / "repaired-worktree-p1/_consensus_seam_posthoc/acceptance/generated_interface_test.go"
    ).exists()
    run_config = json.loads((result.run_directory / "run-config.json").read_text())
    assert run_config["repair"]["source_run"] == str(source_result.run_directory)


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
            "  - name: MC4 failed delivery retention",
            "    capability: message_injection",
            "    command: git diff --check",
            "    failure_code: MESSAGE_INJECTION_RETENTION_FAILED",
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


def test_exception_does_not_replace_latest_audit_export(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = write_project_manifest(tmp_path, repo)
    latest = tmp_path / "runs" / "latest"
    latest.mkdir(parents=True)
    marker = latest / "marker.json"
    marker.write_text('{"source":"previous-complete-run"}\n', encoding="utf-8")
    workflow = ConsensusWorkflow(FakeLLMClient([]), runs_root=tmp_path / "runs")
    with pytest.raises(AgentRuntimeError, match="no response remaining"):
        workflow.analyze(load_project(manifest))
    assert marker.read_text(encoding="utf-8") == (
        '{"source":"previous-complete-run"}\n'
    )
    failed_runs = [
        path
        for path in (tmp_path / "runs").iterdir()
        if path.is_dir() and path.name != "latest"
    ]
    assert len(failed_runs) == 1
    assert (failed_runs[0] / "agent-run-stats.json").is_file()
    failure = json.loads((failed_runs[0] / "failure.json").read_text(encoding="utf-8"))
    assert failure == {"error_type": "AgentRuntimeError", "outcome": "INCOMPLETE"}
