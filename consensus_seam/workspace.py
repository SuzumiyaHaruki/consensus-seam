"""隔离所有 Transformer 修改的 Git worktree。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import PatchMetrics


class WorkspaceError(RuntimeError):
    """无法安全创建或检查隔离 Git worktree 时抛出。"""


def _git(repo: Path, *args: str) -> str:
    """无 shell 执行 Git，并把非零退出统一转换为 WorkspaceError。"""

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
    """返回提交 ID 与 tracked/untracked dirty 状态。

    非 Git 目录返回 None，而不是把“无法验证”误当成 clean；正式实验会据此
    拒绝启动。
    """

    repo = repository.resolve()
    try:
        revision = _git(repo, "rev-parse", "HEAD").strip()
        dirty = bool(_git(repo, "status", "--porcelain").strip())
    except WorkspaceError:
        return {"revision": None, "dirty": None}
    return {"revision": revision, "dirty": dirty}


@dataclass(frozen=True)
class GitWorktree:
    """Agent 2 的 detached 工作区句柄。"""

    original_repository: Path
    path: Path

    @classmethod
    def create(cls, original_repository: Path, destination: Path) -> "GitWorktree":
        """从目标 HEAD 创建 detached worktree，绝不修改原仓库。"""

        repository = original_repository.resolve()
        top_level = Path(_git(repository, "rev-parse", "--show-toplevel").strip()).resolve()
        # 目前 metrics/保护逻辑以仓库根为基准；若 manifest 指向子目录，
        # diff 范围会变得含糊，因此显式要求 repository 是 Git top-level。
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
        """返回相对 HEAD 的完整 patch，并让新文件出现在 diff 中。"""

        # intent-to-add 只记录索引意图，不把文件内容正式 stage/commit。
        _git(self.path, "add", "--intent-to-add", "--", ".")
        return _git(self.path, "diff", "--binary", "--no-ext-diff", "HEAD", "--")

    def modified_existing_go_tests(self) -> list[str]:
        """返回被修改的已有 Go 测试；新增测试允许存在。"""

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
        """仅依据 Git 状态和 numstat 计算补丁侵入性指标。"""

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
