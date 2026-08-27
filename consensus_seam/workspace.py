"""Git worktree isolation for all Transformer modifications."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(RuntimeError):
    """Raised when an isolated Git worktree cannot be prepared or inspected."""


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise WorkspaceError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def git_audit_state(repository: Path) -> dict[str, object]:
    """Return the committed revision and whether tracked/untracked changes exist."""

    repo = repository.resolve()
    try:
        revision = _git(repo, "rev-parse", "HEAD").strip()
        dirty = bool(_git(repo, "status", "--porcelain").strip())
    except WorkspaceError:
        return {"revision": None, "dirty": None}
    return {"revision": revision, "dirty": dirty}


@dataclass(frozen=True)
class GitWorktree:
    original_repository: Path
    path: Path

    @classmethod
    def create(cls, original_repository: Path, destination: Path) -> "GitWorktree":
        repository = original_repository.resolve()
        top_level = Path(_git(repository, "rev-parse", "--show-toplevel").strip()).resolve()
        if top_level != repository:
            raise WorkspaceError(
                f"manifest repository must be the Git top level: {repository} != {top_level}"
            )
        destination = destination.resolve()
        if destination.exists():
            raise WorkspaceError(f"worktree destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        _git(repository, "worktree", "add", "--detach", str(destination), "HEAD")
        return cls(repository, destination)

    def diff(self) -> str:
        # Intent-to-add makes new, non-ignored files visible in a regular patch.
        _git(self.path, "add", "--intent-to-add", "--", ".")
        return _git(self.path, "diff", "--binary", "--no-ext-diff", "HEAD", "--")

    def modified_existing_go_tests(self) -> list[str]:
        """Return tracked Go tests changed from HEAD; newly created tests are allowed."""

        tracked = {
            line
            for line in _git(self.path, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
            if line.endswith("_test.go")
        }
        changed = set(
            _git(self.path, "diff", "--name-only", "HEAD", "--").splitlines()
        )
        return sorted(tracked & changed)
