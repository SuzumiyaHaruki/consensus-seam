"""Git worktree isolation for all Transformer modifications."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import PatchMetrics


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

    def patch_metrics(self) -> PatchMetrics:
        self.diff()
        statuses: dict[str, str] = {}
        for line in _git(self.path, "diff", "--name-status", "HEAD", "--").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                statuses[parts[-1]] = parts[0][0]

        additions: dict[str, tuple[int, int]] = {}
        for line in _git(self.path, "diff", "--numstat", "HEAD", "--").splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added = int(parts[0]) if parts[0].isdigit() else 0
            deleted = int(parts[1]) if parts[1].isdigit() else 0
            additions[parts[2]] = (added, deleted)

        existing_production: list[str] = []
        new_production: list[str] = []
        existing_tests: list[str] = []
        new_tests: list[str] = []
        other: list[str] = []
        production_added = production_deleted = 0
        test_added = test_deleted = 0
        for path, status in sorted(statuses.items()):
            added, deleted = additions.get(path, (0, 0))
            if path.endswith("_test.go"):
                (new_tests if status == "A" else existing_tests).append(path)
                test_added += added
                test_deleted += deleted
            elif path.endswith(".go"):
                (new_production if status == "A" else existing_production).append(path)
                production_added += added
                production_deleted += deleted
            else:
                other.append(path)
        return PatchMetrics(
            existing_production_files_modified=existing_production,
            new_production_files=new_production,
            existing_test_files_modified=existing_tests,
            new_test_files=new_tests,
            other_files_changed=other,
            production_lines_added=production_added,
            production_lines_deleted=production_deleted,
            test_lines_added=test_added,
            test_lines_deleted=test_deleted,
            protocol_core_files_modified=existing_production,
        )
