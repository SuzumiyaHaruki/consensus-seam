from __future__ import annotations

from pathlib import Path

import pytest

from consensus_seam.config import ConfigurationError, load_project


def write_manifest(path: Path, repo: Path, working_directory: str = ".") -> None:
    path.write_text(
        "\n".join(
            [
                "name: mini-raft",
                "language: go",
                "protocol: raft",
                f"repository: {repo}",
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
