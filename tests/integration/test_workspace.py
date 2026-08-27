from __future__ import annotations

import subprocess
from pathlib import Path

from consensus_seam.workspace import GitWorktree


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_worktree_isolates_changes_and_exports_new_files(tmp_path: Path) -> None:
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init")
    (repo / "node.go").write_text("package mini\n", encoding="utf-8")
    git(repo, "add", "node.go")
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

    worktree = GitWorktree.create(repo, tmp_path / "isolated")
    (worktree.path / "pending.go").write_text("package mini\n", encoding="utf-8")
    patch = worktree.diff()
    metrics = worktree.patch_metrics()

    assert "pending.go" in patch
    assert not (repo / "pending.go").exists()
    assert metrics.new_production_files == ["pending.go"]
    assert metrics.production_lines_added == 1
    assert metrics.production_lines_deleted == 0
    assert metrics.protocol_core_files_modified == []

    restored = GitWorktree.create(repo, tmp_path / "restored")
    restored.apply_patch(patch)
    assert (restored.path / "pending.go").read_text(encoding="utf-8") == "package mini\n"
