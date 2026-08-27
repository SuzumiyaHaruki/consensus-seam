"""The single target-language backend supported by v0.1."""

from __future__ import annotations

import json
import os
import re
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
        if symbol.count(".") == 1:
            receiver, method = symbol.split(".", 1)
            valid = all(
                re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item)
                for item in (receiver, method)
            )
            if not valid:
                return []
            return [
                f"{item['file']}:{item['line']}:{receiver}.{method}"
                for item in self.go_find_method(repo, receiver, method)
            ]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
            return []
        return self._search(
            repo,
            rf"\b(func|type|var|const)\s+(\([^)]*\)\s*)?{re.escape(symbol)}\b",
        )

    def find_references(self, repo: Path, symbol: str) -> list[str]:
        if symbol.count(".") == 1:
            receiver, method = symbol.split(".", 1)
            valid = all(
                re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item)
                for item in (receiver, method)
            )
            if valid:
                return [
                    f"{line} [textual candidate for {symbol}; receiver not proven]"
                    for line in self._search(
                        repo,
                        rf"\b{re.escape(method)}\s*\(",
                    )
                ]
        return self._search(repo, rf"\b{re.escape(symbol)}\b")

    def syntax_check(self, repo: Path) -> CommandExecution:
        return self.run_command(repo, "go test -run=^$ ./...")

    def go_find_type(self, repo: Path, name: str) -> list[dict[str, object]]:
        return self._ast_query(repo, "type", name=name)

    def go_find_method(
        self,
        repo: Path,
        receiver: str,
        method: str,
    ) -> list[dict[str, object]]:
        return self._ast_query(repo, "method", name=method, receiver=receiver)

    @staticmethod
    def _ast_query(
        repo: Path,
        kind: str,
        *,
        name: str,
        receiver: str | None = None,
    ) -> list[dict[str, object]]:
        helper = Path(__file__).resolve().parent / "go_ast" / "main.go"
        command = [
            "go",
            "run",
            str(helper),
            "-root",
            str(repo),
            "-kind",
            kind,
            "-name",
            name,
        ]
        if receiver is not None:
            command.extend(["-receiver", receiver])
        try:
            completed = subprocess.run(
                command,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Go executable is required for AST symbol queries") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Go AST symbol query timed out") from exc
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Go AST symbol query failed")
        payload = json.loads(completed.stdout)
        if not isinstance(payload, list):
            raise RuntimeError("Go AST helper returned an invalid response")
        return payload

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
            return GoBackend._python_search(repo, pattern)
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or "rg search failed")
        matches = completed.stdout.splitlines()
        return matches if matches else GoBackend._python_search(repo, pattern)

    @staticmethod
    def _python_search(repo: Path, pattern: str) -> list[str]:
        expression = re.compile(pattern)
        matches: list[str] = []
        for current, directories, filenames in os.walk(repo, followlinks=False):
            directories[:] = sorted(
                name for name in directories if name not in {".git", "vendor"}
            )
            for filename in sorted(filenames):
                if not filename.endswith(".go"):
                    continue
                path = Path(current) / filename
                try:
                    relative = path.relative_to(repo).as_posix()
                    with path.open("r", encoding="utf-8", errors="replace") as handle:
                        for line_number, line in enumerate(handle, start=1):
                            if expression.search(line):
                                matches.append(
                                    f"./{relative}:{line_number}:{line.rstrip()}"
                                )
                except OSError:
                    continue
        return matches
