"""The single target-language backend supported by v0.1."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from ..models import CommandExecution
from .base import LanguageBackend


class GoBackend(LanguageBackend):
    def build(self, repo: Path, command: str) -> CommandExecution:
        return self.run_command(repo, command)

    def test(self, repo: Path, command: str) -> CommandExecution:
        return self.run_command(repo, command)

    def format_changed_files(self, repo: Path) -> CommandExecution:
        started = time.monotonic()
        changed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "*.go"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if changed.returncode != 0:
            return CommandExecution(
                command="git diff --name-only HEAD -- *.go",
                returncode=changed.returncode,
                stdout=changed.stdout,
                stderr=changed.stderr,
                duration_seconds=time.monotonic() - started,
            )
        files = [line for line in changed.stdout.splitlines() if line]
        if not files:
            return CommandExecution(
                command="gofmt -w <changed-go-files>",
                returncode=0,
                duration_seconds=time.monotonic() - started,
            )
        formatted = subprocess.run(
            ["gofmt", "-w", *files],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        return CommandExecution(
            command="gofmt -w " + " ".join(files),
            returncode=formatted.returncode,
            stdout=formatted.stdout,
            stderr=formatted.stderr,
            duration_seconds=time.monotonic() - started,
        )

    def find_symbol(self, repo: Path, symbol: str) -> list[str]:
        return self._search(repo, rf"\b(func|type|var|const)\s+(\([^)]*\)\s*)?{symbol}\b")

    def find_references(self, repo: Path, symbol: str) -> list[str]:
        return self._search(repo, rf"\b{symbol}\b")

    def syntax_check(self, repo: Path) -> CommandExecution:
        return self.run_command(repo, "go test -run=^$ ./...")

    @staticmethod
    def _search(repo: Path, pattern: str) -> list[str]:
        try:
            completed = subprocess.run(
                ["rg", "--line-number", "--glob", "*.go", pattern, "."],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return []
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or "rg search failed")
        return completed.stdout.splitlines()
