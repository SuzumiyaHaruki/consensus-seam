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

    assert "pending.go" in patch
    assert not (repo / "pending.go").exists()
