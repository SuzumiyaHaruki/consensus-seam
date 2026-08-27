from __future__ import annotations

import json
import subprocess
from pathlib import Path

from consensus_seam.languages.go import GoBackend
from consensus_seam.tools import (
    MAX_TOOL_OUTPUT,
    LocalTool,
    ToolInput,
    ToolRegistry,
    analyzer_tools,
    reviewer_tools,
    transformer_tools,
)


def names(registry: object) -> set[str]:
    return {item["function"]["name"] for item in registry.definitions}  # type: ignore[attr-defined]


def test_role_scoped_tool_permissions_and_path_containment(tmp_path: Path) -> None:
    source = tmp_path / "source"
    patched = tmp_path / "patched"
    source.mkdir()
    patched.mkdir()
    (source / "node.go").write_text("package mini\n", encoding="utf-8")
    backend = GoBackend()

    analyzer = analyzer_tools(source, backend)
    assert "write_file" not in names(analyzer)
    listed = json.loads(
        analyzer.execute("list_files", '{"scope":"source","path":"."}')
    )
    assert listed["result"]["files"] == ["node.go"]
    escaped = json.loads(
        analyzer.execute("read_file", '{"scope":"source","path":"../secret"}')
    )
    assert escaped["ok"] is False
    forbidden_check = json.loads(
        analyzer.execute(
            "run_readonly_check",
            '{"scope":"source","check":"go_test","package":"./..."}',
        )
    )
    assert forbidden_check["ok"] is False

    transformer = transformer_tools(patched, backend)
    assert {"write_file", "apply_patch"} <= names(transformer)
    written = json.loads(
        transformer.execute(
            "write_file",
            '{"path":"testcontrol/pending.go","content":"package testcontrol\\n"}',
        )
    )
    assert written["ok"] is True
    assert (patched / "testcontrol" / "pending.go").is_file()

    reviewer = reviewer_tools(source, patched, backend)
    assert "write_file" not in names(reviewer)
    read = json.loads(
        reviewer.execute(
            "read_file",
            '{"scope":"patched","path":"testcontrol/pending.go"}',
        )
    )
    assert read["ok"] is True


def test_apply_patch_cannot_escape_or_delete(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "node.go").write_text("package mini\n", encoding="utf-8")
    registry = transformer_tools(repo, GoBackend())
    safe_patch = """diff --git a/node.go b/node.go
--- a/node.go
+++ b/node.go
@@ -1 +1,3 @@
 package mini
+
+func Tick() {}
"""
    applied = json.loads(
        registry.execute("apply_patch", json.dumps({"patch": safe_patch}))
    )
    assert applied["ok"] is True
    assert "func Tick" in (repo / "node.go").read_text(encoding="utf-8")

    delete_patch = """diff --git a/node.go b/node.go
deleted file mode 100644
--- a/node.go
+++ /dev/null
@@ -1,3 +0,0 @@
-package mini
-
-func Tick() {}
"""
    rejected = json.loads(
        registry.execute("apply_patch", json.dumps({"patch": delete_patch}))
    )
    assert rejected["ok"] is False
    assert (repo / "node.go").exists()


def test_all_tool_results_are_bounded() -> None:
    registry = ToolRegistry(
        [
            LocalTool(
                "large_result",
                "return a deliberately large result",
                ToolInput,
                lambda _: "测" * MAX_TOOL_OUTPUT,
            )
        ]
    )
    serialized = registry.execute("large_result", "{}")
    payload = json.loads(serialized)
    assert len(serialized.encode("utf-8")) <= MAX_TOOL_OUTPUT
    assert payload["truncated"] is True
