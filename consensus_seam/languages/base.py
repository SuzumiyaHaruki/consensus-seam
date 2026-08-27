"""Thin target-language boundary used by the verifier and workspace code."""

from __future__ import annotations

import shlex
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path

from ..models import CommandExecution


class LanguageBackend(ABC):
    @abstractmethod
    def build(self, repo: Path, command: str) -> CommandExecution:
        raise NotImplementedError

    @abstractmethod
    def test(self, repo: Path, command: str) -> CommandExecution:
        raise NotImplementedError

    @abstractmethod
    def format_changed_files(self, repo: Path) -> CommandExecution:
        raise NotImplementedError

    @abstractmethod
    def find_symbol(self, repo: Path, symbol: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def find_references(self, repo: Path, symbol: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def syntax_check(self, repo: Path) -> CommandExecution:
        raise NotImplementedError

    def run_command(
        self,
        repo: Path,
        command: str,
        *,
        timeout_seconds: float = 600,
    ) -> CommandExecution:
        """Execute a manifest command without an implicit shell."""

        started = time.monotonic()
        try:
            argv = shlex.split(command)
            if not argv:
                raise ValueError("command cannot be empty")
            completed = subprocess.run(
                argv,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            return CommandExecution(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_seconds=time.monotonic() - started,
            )
        except FileNotFoundError as exc:
            return CommandExecution(
                command=command,
                returncode=127,
                stderr=str(exc),
                duration_seconds=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return CommandExecution(
                command=command,
                returncode=124,
                stdout=stdout,
                stderr=f"{stderr}\ncommand timed out after {timeout_seconds:g}s".strip(),
                duration_seconds=time.monotonic() - started,
            )
