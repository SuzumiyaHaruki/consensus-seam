"""按角色隔离的源码检查与 worktree 编辑工具。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .languages.go import GoBackend


# 返回给模型的单次工具结果上限，防止一次读取占满上下文。
MAX_TOOL_OUTPUT = 64000
# Agent 2 单次写文件/patch 的 UTF-8 上限；字符数校验之后还会再检查字节数。
MAX_WRITE_BYTES = 2 * 1024 * 1024


class ToolInput(BaseModel):
    """所有工具参数的严格基类，拒绝模型创造未声明参数。"""

    model_config = ConfigDict(extra="forbid")


class ScopedPathInput(ToolInput):
    """带角色 scope 的相对路径参数。"""

    scope: str = Field(min_length=1, max_length=100)
    path: str = Field(default=".", min_length=1, max_length=4096)


class ListFilesInput(ScopedPathInput):
    max_files: int = Field(default=2000, ge=1, le=5000)


class ReadFileInput(ScopedPathInput):
    start: int = Field(default=1, ge=1)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def bounded_range(self) -> "ReadFileInput":
        # 每次最多 500 行，鼓励 Agent 精确读取符号附近而非反复全文加载。
        if self.end is not None and self.end < self.start:
            raise ValueError("end must not precede start")
        if self.end is not None and self.end - self.start + 1 > 500:
            raise ValueError("read_file is limited to 500 lines per call")
        return self


class SearchTextInput(ScopedPathInput):
    query: str = Field(min_length=1, max_length=1000)
    max_results: int = Field(default=200, ge=1, le=500)


class SymbolInput(ToolInput):
    scope: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=300)


class GoTypeInput(ToolInput):
    scope: str = Field(min_length=1, max_length=100)
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class GoMethodInput(ToolInput):
    scope: str = Field(min_length=1, max_length=100)
    receiver: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    method: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class ReadonlyCheckInput(ToolInput):
    scope: str = Field(min_length=1, max_length=100)
    check: Literal["go_test", "go_test_compile", "go_doc"]
    package: str = Field(default="./...", min_length=1, max_length=500)
    run: str | None = Field(default=None, max_length=500)
    symbol: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_focused_test(self) -> "ReadonlyCheckInput":
        if self.check == "go_test":
            if not self.run:
                raise ValueError(
                    "go_test requires a focused run pattern; use "
                    "go_test_compile for package-wide compilation"
                )
            if any(char.isspace() for char in self.run):
                raise ValueError(
                    "go_test run is one regex, not a CLI argument string; "
                    "flags such as -v or -count are not supported"
                )
            alternatives = self.run.split("|")
            if len(alternatives) > 12:
                raise ValueError("go_test run may name at most 12 focused tests")
            for alternative in alternatives:
                name = alternative.removeprefix("^").removesuffix("$")
                if (
                    not name.startswith("Test")
                    or len(name) <= len("Test")
                    or not name.isidentifier()
                ):
                    raise ValueError(
                        "go_test run must be an exact TestName or an alternation "
                        "of exact TestName values"
                    )
        elif self.run is not None:
            raise ValueError("run is only valid with go_test")
        return self


class ApplyPatchInput(ToolInput):
    patch: str = Field(min_length=1, max_length=MAX_WRITE_BYTES)


class WriteFileInput(ToolInput):
    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=MAX_WRITE_BYTES)


@dataclass(frozen=True)
class LocalTool:
    """一个工具的名称、描述、输入 Schema 与本地 handler。"""

    name: str
    description: str
    input_model: type[ToolInput]
    handler: Callable[[ToolInput], Any]

    def definition(self) -> dict[str, Any]:
        """转换成 OpenAI-compatible function tool 定义。"""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }


class ToolRegistry:
    """某个 Agent 角色可见的工具白名单。"""

    def __init__(self, tools: list[LocalTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("tool names must be unique")

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return [tool.definition() for tool in self._tools.values()]

    def execute(self, name: str, raw_arguments: str) -> str:
        """解析参数、执行 handler，并统一返回有界 JSON。

        工具错误被转换为 ok=false 返回给模型，使模型可以修正路径或 patch；
        未列出的异常仍向上抛出，避免吞掉框架编程错误。
        """

        tool = self._tools.get(name)
        if tool is None:
            return self._bounded_json({"ok": False, "error": f"unknown tool: {name}"})
        try:
            raw = json.loads(raw_arguments)
            arguments = tool.input_model.model_validate(raw)
            value = tool.handler(arguments)
            return self._bounded_json({"ok": True, "result": value})
        except (
            json.JSONDecodeError,
            ValidationError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            subprocess.SubprocessError,
        ) as exc:
            return self._bounded_json(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            )

    @staticmethod
    def _bounded_json(payload: dict[str, Any]) -> str:
        """按 UTF-8 字节数截断响应，并保留原始大小供审计。"""

        serialized = json.dumps(payload, ensure_ascii=False)
        original_bytes = len(serialized.encode("utf-8"))
        if original_bytes <= MAX_TOOL_OUTPUT:
            return serialized
        preview_limit = MAX_TOOL_OUTPUT - 512
        while preview_limit > 0:
            preview = serialized.encode("utf-8")[:preview_limit].decode(
                "utf-8", errors="ignore"
            )
            bounded = json.dumps(
                {
                    "ok": payload.get("ok", True),
                    "truncated": True,
                    "original_bytes": original_bytes,
                    "preview": preview,
                },
                ensure_ascii=False,
            )
            if len(bounded.encode("utf-8")) <= MAX_TOOL_OUTPUT:
                return bounded
            preview_limit -= 512
        return '{"ok":false,"truncated":true,"error":"tool output exceeded limit"}'


class LocalToolFactory:
    """根据角色 scope 和写权限构造工具集合。

    scope 名称（source/worktree/original/patched）由 Controller 创建，模型只
    能在已注册根目录中选择，不能自行提供任意绝对路径。
    """

    def __init__(
        self,
        scopes: dict[str, Path],
        *,
        backend: GoBackend,
        writable_scope: str | None = None,
        allowed_checks: set[str] | None = None,
    ) -> None:
        self.scopes = {name: root.resolve() for name, root in scopes.items()}
        self.backend = backend
        self.writable_scope = writable_scope
        self.allowed_checks = allowed_checks or set()

    def read_only_registry(self, *, include_checks: bool) -> ToolRegistry:
        """创建 Analyzer/Reviewer 使用的只读工具集。"""

        tools = [
            LocalTool(
                "list_files",
                self._scope_help("List source files under a relative path."),
                ListFilesInput,
                self._list_files,
            ),
            LocalTool(
                "read_file",
                self._scope_help("Read a bounded source-file line range."),
                ReadFileInput,
                self._read_file,
            ),
            LocalTool(
                "search_text",
                self._scope_help("Search literal text with ripgrep."),
                SearchTextInput,
                self._search_text,
            ),
            LocalTool(
                "find_symbol",
                self._scope_help("Find a Go symbol; Receiver.Method uses Go AST."),
                SymbolInput,
                self._find_symbol,
            ),
            LocalTool(
                "find_references",
                self._scope_help("Find textual Go references to a symbol."),
                SymbolInput,
                self._find_references,
            ),
            LocalTool(
                "go_find_type",
                self._scope_help("Find exact Go type declarations using go/parser."),
                GoTypeInput,
                self._go_find_type,
            ),
            LocalTool(
                "go_find_method",
                self._scope_help("Find an exact receiver method using go/parser."),
                GoMethodInput,
                self._go_find_method,
            ),
        ]
        if include_checks:
            tools.append(
                LocalTool(
                    "run_readonly_check",
                    self._scope_help(
                        "Run an allowlisted focused go_test (exact TestName required), "
                        "package compile, or go_doc check."
                    ),
                    ReadonlyCheckInput,
                    self._run_readonly_check,
                )
            )
        return ToolRegistry(tools)

    def transformer_registry(self) -> ToolRegistry:
        """在只读工具基础上增加受限 patch 与文件写入。"""

        if self.writable_scope is None:
            raise ValueError("transformer tools require a writable scope")
        tools = list(self.read_only_registry(include_checks=True)._tools.values())
        tools.extend(
            [
                LocalTool(
                    "apply_patch",
                    "Apply a non-deleting unified diff inside the isolated worktree.",
                    ApplyPatchInput,
                    self._apply_patch,
                ),
                LocalTool(
                    "write_file",
                    "Create or replace one UTF-8 file inside the isolated worktree.",
                    WriteFileInput,
                    self._write_file,
                ),
            ]
        )
        return ToolRegistry(tools)

    def _scope_help(self, description: str) -> str:
        """把当前角色允许的 scope 写进工具描述，减少无效调用。"""

        return f"{description} Allowed scopes: {', '.join(sorted(self.scopes))}."

    def _root(self, scope: str) -> Path:
        """把模型给出的 scope 映射为 Controller 预注册根目录。"""

        try:
            return self.scopes[scope]
        except KeyError as exc:
            raise ValueError(f"unknown scope {scope!r}; expected one of {sorted(self.scopes)}") from exc

    def _resolve(self, scope: str, path: str, *, writable: bool = False) -> Path:
        """解析相对路径并执行 containment/写权限校验。

        resolve 会展开符号链接，再用 relative_to 验证最终目标仍位于根目录；
        因此 `..` 或指向仓库外的 symlink 都不能越界。
        """

        root = self._root(scope)
        relative = Path(path)
        if relative.is_absolute() or ".git" in relative.parts:
            raise ValueError("path must be relative and cannot access .git")
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("path escapes the allowed repository scope") from exc
        if writable and scope != self.writable_scope:
            raise ValueError(f"scope {scope!r} is read-only")
        return resolved

    def _list_files(self, value: ToolInput) -> dict[str, Any]:
        """确定性列出文件，跳过 .git 且不跟随目录符号链接。"""

        args = ListFilesInput.model_validate(value)
        root = self._root(args.scope)
        start = self._resolve(args.scope, args.path)
        if not start.is_dir():
            raise ValueError(f"not a directory: {args.path}")
        files: list[str] = []
        truncated = False
        for current, directories, filenames in os.walk(start, followlinks=False):
            directories[:] = sorted(name for name in directories if name != ".git")
            for filename in sorted(filenames):
                candidate = Path(current) / filename
                try:
                    candidate.resolve().relative_to(root)
                except ValueError:
                    continue
                files.append(candidate.relative_to(root).as_posix())
                if len(files) >= args.max_files:
                    truncated = True
                    return {"files": files, "truncated": truncated}
        return {"files": files, "truncated": truncated}

    def _read_file(self, value: ToolInput) -> dict[str, Any]:
        """读取带行号的有限区间，供模型构造精确代码证据/patch context。"""

        args = ReadFileInput.model_validate(value)
        path = self._resolve(args.scope, args.path)
        if not path.is_file():
            raise ValueError(f"not a file: {args.path}")
        end = args.end or args.start + 499
        selected: list[str] = []
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if number < args.start:
                    continue
                if number > end:
                    break
                selected.append(f"{number}: {line.rstrip()}")
        joined = "\n".join(selected)
        truncated = len(joined) > MAX_TOOL_OUTPUT
        if truncated:
            joined = joined[:MAX_TOOL_OUTPUT]
            selected = joined.splitlines()
        return {
            "path": args.path,
            "start": args.start,
            "end": end,
            "lines": selected,
            "truncated": truncated,
        }

    def _search_text(self, value: ToolInput) -> dict[str, Any]:
        """执行 fixed-string 搜索；rg 不存在时使用 Python 回退。"""

        args = SearchTextInput.model_validate(value)
        path = self._resolve(args.scope, args.path)
        command = [
            "rg",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            "--fixed-strings",
            "--",
            args.query,
            str(path),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self._root(args.scope),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except FileNotFoundError:
            lines = self._python_fixed_string_search(
                self._root(args.scope),
                path,
                args.query,
                args.max_results + 1,
            )
        else:
            if completed.returncode not in (0, 1):
                raise RuntimeError(completed.stderr.strip() or "rg search failed")
            lines = completed.stdout.splitlines()
        output = lines[: args.max_results]
        joined = "\n".join(output)
        if len(joined) > MAX_TOOL_OUTPUT:
            joined = joined[:MAX_TOOL_OUTPUT]
            output = joined.splitlines()
        return {"matches": output, "truncated": len(lines) > len(output)}

    @staticmethod
    def _python_fixed_string_search(
        root: Path,
        start: Path,
        query: str,
        limit: int,
    ) -> list[str]:
        """无 ripgrep 时在允许根目录内做确定性纯文本搜索。

        回退路径沿用与 read/list 相同的 containment 边界，并多取一条结果，
        让调用者可以准确设置 truncated，而不必扫描完整仓库。
        """

        candidates: list[Path] = []
        if start.is_file():
            candidates.append(start)
        elif start.is_dir():
            for current, directories, filenames in os.walk(start, followlinks=False):
                directories[:] = sorted(name for name in directories if name != ".git")
                candidates.extend(Path(current) / name for name in sorted(filenames))

        matches: list[str] = []
        for candidate in candidates:
            try:
                candidate.resolve().relative_to(root)
                with candidate.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if query not in line:
                            continue
                        matches.append(f"{candidate}:{line_number}:{line.rstrip()}")
                        if len(matches) >= limit:
                            return matches
            except (OSError, ValueError):
                continue
        return matches

    def _find_symbol(self, value: ToolInput) -> list[str]:
        """委托语言后端查找声明。"""

        args = SymbolInput.model_validate(value)
        return self.backend.find_symbol(self._root(args.scope), args.symbol)[:500]

    def _find_references(self, value: ToolInput) -> list[str]:
        args = SymbolInput.model_validate(value)
        return self.backend.find_references(self._root(args.scope), args.symbol)[:500]

    def _go_find_type(self, value: ToolInput) -> list[dict[str, object]]:
        args = GoTypeInput.model_validate(value)
        return self.backend.go_find_type(self._root(args.scope), args.name)

    def _go_find_method(self, value: ToolInput) -> list[dict[str, object]]:
        args = GoMethodInput.model_validate(value)
        return self.backend.go_find_method(self._root(args.scope), args.receiver, args.method)

    def _run_readonly_check(self, value: ToolInput) -> dict[str, Any]:
        """执行角色白名单内的 Go 查询/测试命令。

        Analyzer 只允许 go_doc；Transformer 才能运行 go_test。参数通过正则
        限制后使用 argv 调用，不经过 shell。
        """

        args = ReadonlyCheckInput.model_validate(value)
        if args.check not in self.allowed_checks:
            raise ValueError(
                f"check {args.check!r} is not allowed for this Agent role; "
                f"allowed: {sorted(self.allowed_checks)}"
            )
        valid_package = re.fullmatch(r"[A-Za-z0-9_./*?\[\]-]+", args.package)
        if not valid_package or args.package.startswith("-"):
            raise ValueError("invalid Go package pattern")
        if args.symbol is not None and not re.fullmatch(r"[A-Za-z0-9_./-]+", args.symbol):
            raise ValueError("invalid go_doc symbol")
        if args.check == "go_doc":
            command = ["go", "doc", args.symbol or args.package]
        else:
            command = ["go", "test"]
            if args.check == "go_test_compile":
                command.append("-run=^$")
            elif args.run is not None:
                names = [
                    item.removeprefix("^").removesuffix("$")
                    for item in args.run.split("|")
                ]
                command.append("-run=^(?:" + "|".join(map(re.escape, names)) + ")$")
            command.append(args.package)
        completed = subprocess.run(
            command,
            cwd=self._root(args.scope),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-MAX_TOOL_OUTPUT:],
            "stderr": completed.stderr[-MAX_TOOL_OUTPUT:],
        }

    def _apply_patch(self, value: ToolInput) -> dict[str, Any]:
        """先 `git apply --check`，通过后再真正应用非删除 patch。"""

        args = ApplyPatchInput.model_validate(value)
        if len(args.patch.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ValueError(f"UTF-8 patch exceeds {MAX_WRITE_BYTES} bytes")
        root = self._root(self.writable_scope or "")
        self._validate_patch_paths(args.patch)
        for mode in ("--check", "--apply"):
            # 模型生成的 unified diff 偶尔只有 hunk 行数统计不准确；
            # --recount 只重算行数，仍然要求文件路径和上下文完全匹配。
            command = ["git", "apply", "--recount", "--whitespace=nowarn"]
            if mode == "--check":
                command.append("--check")
            completed = subprocess.run(
                command,
                cwd=root,
                input=args.patch,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or f"git apply {mode} failed")
        return {"applied": True}

    @staticmethod
    def _validate_patch_paths(patch: str) -> None:
        """拒绝删除、重命名、二进制 patch 和越界路径。"""

        forbidden = (
            "deleted file mode",
            "rename from ",
            "rename to ",
            "GIT binary patch",
        )
        if any(marker in patch for marker in forbidden) or "+++ /dev/null" in patch:
            raise ValueError("deleting, renaming, and binary patches are not allowed")
        for line in patch.splitlines():
            if not line.startswith(("--- ", "+++ ")):
                continue
            raw = line[4:].split("\t", 1)[0]
            if raw == "/dev/null":
                continue
            path = Path(raw[2:] if raw.startswith(("a/", "b/")) else raw)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
                raise ValueError(f"unsafe patch path: {raw}")

    def _write_file(self, value: ToolInput) -> dict[str, Any]:
        """在唯一可写 scope 内创建或覆盖一个 UTF-8 文件。"""

        args = WriteFileInput.model_validate(value)
        encoded = args.content.encode("utf-8")
        if len(encoded) > MAX_WRITE_BYTES:
            raise ValueError(f"UTF-8 content exceeds {MAX_WRITE_BYTES} bytes")
        scope = self.writable_scope or ""
        path = self._resolve(scope, args.path, writable=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.content, encoding="utf-8")
        return {"path": args.path, "bytes": len(encoded)}


def analyzer_tools(repository: Path, backend: GoBackend) -> ToolRegistry:
    """Agent 1：目标源码只读，且不能运行目标测试。"""

    return LocalToolFactory(
        {"source": repository},
        backend=backend,
        allowed_checks={"go_doc"},
    ).read_only_registry(include_checks=True)


def transformer_tools(worktree: Path, backend: GoBackend) -> ToolRegistry:
    """Agent 2：只可写 detached worktree，并可运行受限 Go 检查。"""

    return LocalToolFactory(
        {"worktree": worktree},
        backend=backend,
        writable_scope="worktree",
        allowed_checks={"go_test", "go_test_compile", "go_doc"},
    ).transformer_registry()


def reviewer_tools(original: Path, patched: Path, backend: GoBackend) -> ToolRegistry:
    """Agent 3：同时读取 original/patched，但没有写入和命令执行工具。"""

    return LocalToolFactory(
        {"original": original, "patched": patched}, backend=backend
    ).read_only_registry(include_checks=False)
