"""Materialize evaluator-only verification files after Agent 3 finishes."""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import LoadedProject


class VerificationFixtureError(RuntimeError):
    pass


@contextmanager
def materialized_verification_fixtures(
    project: LoadedProject,
    worktree: Path,
) -> Iterator[None]:
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
            if destination.exists():
                raise VerificationFixtureError(
                    f"fixture destination already exists: {fixture.destination}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixture.source, destination)
            created.append(destination)
        yield
    finally:
        for path in reversed(created):
            path.unlink(missing_ok=True)
            parent = path.parent
            while parent != root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
