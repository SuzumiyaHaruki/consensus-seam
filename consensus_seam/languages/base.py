"""Thin target-language boundary used by the verifier and workspace code."""

from __future__ import annotations

import shlex
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path

from ..models import CommandExecution


class LanguageBackend(ABC):
    """目标语言适配层。

    Workflow/Verifier 只依赖这些方法；当前 v0.1 仅提供 GoBackend。公共命令
    执行放在基类，符号、格式化等语言语义由子类实现。
    """

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

    def run_command(
        self,
        repo: Path,
        command: str,
        *,
        timeout_seconds: float = 600,
    ) -> CommandExecution:
        """不经过 shell 执行 manifest 命令并捕获结构化结果。

        shlex 只把受版本控制的字符串拆成 argv，不支持管道、重定向或命令
        替换。缺少可执行文件和超时也转换为普通返回码供 Verifier 路由。
        """

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
