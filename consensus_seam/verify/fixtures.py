"""Materialize evaluator-only verification files after Agent 3 finishes."""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import LoadedProject


class VerificationFixtureError(RuntimeError):
    """隐藏 fixture 无法安全复制或清除时抛出。"""

    pass


@contextmanager
def materialized_verification_fixtures(
    project: LoadedProject,
    worktree: Path,
) -> Iterator[None]:
    """仅在 with 作用域内物化 evaluator-only 文件。

    Agent 3 返回后才进入该 context；finally 会删除文件并自底向上清理空
    目录，因此 Verifier 异常也不会把 oracle 留给下一轮 Agent 2。
    """

    root = worktree.resolve()
    created: list[Path] = []
    try:
        for fixture in project.verification_fixtures:
            destination = (root / fixture.destination).resolve()
            try:
                destination.relative_to(root)
            except ValueError as exc:
                raise VerificationFixtureError(
                    f"fixture destination escapes worktree: {fixture.destination}"
                ) from exc
            # 绝不覆盖 Agent 已创建的同名路径；否则既会破坏候选，也可能让
            # 候选通过预置路径干扰隐藏 oracle。
            if destination.exists():
                raise VerificationFixtureError(
                    f"fixture destination already exists: {fixture.destination}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixture.source, destination)
            created.append(destination)
        yield
    finally:
        # 只删除本 context 实际创建的文件；遇到非空父目录立即停止。
        for path in reversed(created):
            path.unlink(missing_ok=True)
            parent = path.parent
            while parent != root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
