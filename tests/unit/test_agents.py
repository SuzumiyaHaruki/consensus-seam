from __future__ import annotations

import json
from pathlib import Path

import pytest

from consensus_seam.agents.analyzer import CapabilityAnalyzer
from consensus_seam.agents.transformer import LowIntrusionTransformer
from consensus_seam.config import LoadedProject
from consensus_seam.llm.client import FakeLLMClient
from consensus_seam.languages.go import GoBackend
from consensus_seam.models import (
    AgentModelConfig,
    CapabilitySpec,
    ModificationPolicy,
    ProjectManifest,
)
from tests.helpers import capability_report


def loaded_project(tmp_path: Path) -> LoadedProject:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = ProjectManifest.model_validate(
        {
            "name": "mini-raft",
            "language": "go",
            "protocol": "raft",
            "repository": str(repo),
            "system_boundary": {
                "kind": "protocol_library",
                "description": "Mini Raft protocol core only",
            },
            "build": {"command": "go test ./..."},
            "test": {"command": "go test ./..."},
        }
    )
    definitions = {
        name: {"description": f"description for {name}"}
        for name in capability_report()["capabilities"]
    }
    return LoadedProject(
        manifest_path=tmp_path / "project.yaml",
        manifest=manifest,
        repository=repo,
        working_directory=repo,
        capabilities=CapabilitySpec.model_validate(
            {"version": 1, "capabilities": definitions, "prerequisites": {}}
        ),
        modification_policy=ModificationPolicy(allowed=["add_test_hook"], forbidden=[]),
        protocol_brief={"protocol": "raft"},
    )


def test_analyzer_retries_invalid_json(tmp_path: Path) -> None:
    client = FakeLLMClient(["not-json", json.dumps(capability_report())])
    analyzer = CapabilityAnalyzer(
        client,
        model=AgentModelConfig(model="fake-analyzer"),
        backend=GoBackend(),
    )
    result = analyzer.analyze(loaded_project(tmp_path))
    assert result.target == "mini-raft"
    assert len(client.calls) == 2
    assert client.calls[0]["invocation_id"] == "analyzer-attempt1"
    assert client.calls[1]["invocation_id"] == "analyzer-attempt2"
    assert "previous response was rejected" in client.calls[1]["user_prompt"]
    assert "Previous response:\nnot-json" in client.calls[1]["user_prompt"]


def test_analyzer_retries_target_name_mismatch(tmp_path: Path) -> None:
    wrong = capability_report()
    wrong["target"] = "mini-raft with explanatory suffix"
    client = FakeLLMClient([json.dumps(wrong), json.dumps(capability_report())])
    analyzer = CapabilityAnalyzer(
        client,
        model=AgentModelConfig(model="fake-analyzer"),
        backend=GoBackend(),
    )
    result = analyzer.analyze(loaded_project(tmp_path), invocation_id="analyzer-a1")
    assert result.target == "mini-raft"
    assert [call["invocation_id"] for call in client.calls] == [
        "analyzer-a1-attempt1",
        "analyzer-a1-attempt2",
    ]
    assert "does not match project" in client.calls[1]["user_prompt"]


def test_transformer_retries_overreported_capabilities_as_json_correction(
    tmp_path: Path,
) -> None:
    project = loaded_project(tmp_path)
    report = CapabilityAnalyzer(
        FakeLLMClient([json.dumps(capability_report())]),
        model=AgentModelConfig(model="fake-analyzer"),
        backend=GoBackend(),
    ).analyze(project)
    client = FakeLLMClient(
        [
            json.dumps(
                {
                    "message_capture": {
                        "implemented": True,
                        "capture_boundary": {"symbol": "ProtocolOutput"},
                    },
                    "message_injection": {"implemented": True},
                }
            ),
            json.dumps(
                {
                    "message_injection": {
                        "implemented": True,
                        "entrypoint": {"symbol": "InjectCached"},
                    }
                }
            ),
        ]
    )
    transformer = LowIntrusionTransformer(
        client,
        model=AgentModelConfig(model="fake-transformer"),
        backend=GoBackend(),
    )
    result = transformer.transform(project, report, tmp_path / "worktree")

    assert result.message_injection is not None
    assert len(client.calls) == 2
    assert "cover exactly" in client.calls[1]["user_prompt"]
