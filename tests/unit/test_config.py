from __future__ import annotations

from pathlib import Path

import pytest

from consensus_seam.config import ConfigurationError, load_posthoc_checks, load_project


def write_manifest(path: Path, repo: Path, working_directory: str = ".") -> None:
    path.write_text(
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
                f"working_directory: {working_directory}",
            ]
        ),
        encoding="utf-8",
    )


def test_load_project_resolves_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = tmp_path / "project.yaml"
    write_manifest(manifest, repo)
    loaded = load_project(manifest)
    assert loaded.repository == repo.resolve()
    assert set(loaded.capabilities.capabilities) >= {"message_capture", "external_input"}


def test_working_directory_cannot_escape_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = tmp_path / "project.yaml"
    write_manifest(manifest, repo, "..")
    with pytest.raises(ConfigurationError, match="must stay inside repository"):
        load_project(manifest)


def test_system_boundary_is_required(tmp_path: Path) -> None:
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
                "build: {command: 'go test ./...'}",
                "test: {command: 'go test ./...'}",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="system_boundary"):
        load_project(manifest)


def test_transform_capabilities_must_be_unique(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = tmp_path / "project.yaml"
    write_manifest(manifest, repo)
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "\ntransform_capabilities:\n"
        + "  - message_capture\n"
        + "  - message_capture\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="must be unique"):
        load_project(manifest)


def test_load_posthoc_checks_resolves_external_fixtures(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    fixture = tmp_path / "post_hoc_test.go"
    fixture.write_text("package acceptance_test\n", encoding="utf-8")
    manifest = tmp_path / "post-hoc-checks.yaml"
    manifest.write_text(
        "\n".join(
            [
                "capability_checks:",
                "  - name: generated injection",
                "    capability: message_injection",
                "    command: go test ./posthoc",
                "    failure_code: MESSAGE_INJECTION_FAILED",
                "verification_fixtures:",
                f"  - source: {fixture.name}",
                "    destination: posthoc/post_hoc_test.go",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_posthoc_checks(manifest, repository=repo)

    assert loaded.verification_fixtures[0].source == fixture.resolve()
    assert loaded.manifest.capability_checks[0].capability == "message_injection"
