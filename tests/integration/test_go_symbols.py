from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import consensus_seam.languages.go as go_module
from consensus_seam.languages.go import GoBackend


def test_go_ast_finds_pointer_receiver_method(tmp_path: Path, monkeypatch: object) -> None:
    cache = tmp_path.parent / f"{tmp_path.name}-gocache"
    monkeypatch.setenv("GOCACHE", str(cache))  # type: ignore[attr-defined]
    (tmp_path / "rawnode.go").write_text(
        """package raft

type RawNode struct{}

func (rn *RawNode) Ready() {}
func (rn RawNode) Tick() {}

func use(rn *RawNode) { rn.Ready() }
""",
        encoding="utf-8",
    )
    backend = GoBackend()
    ready = backend.go_find_method(tmp_path, "RawNode", "Ready")
    assert ready == [
        {
            "kind": "method",
            "receiver": "RawNode",
            "name": "Ready",
            "file": "rawnode.go",
            "line": 5,
        }
    ]
    assert backend.find_symbol(tmp_path, "RawNode.Tick") == [
        "rawnode.go:6:RawNode.Tick"
    ]
    # The deterministic fallback must preserve references when rg is unavailable
    # or transiently reports no matches.
    monkeypatch.setattr(  # type: ignore[attr-defined]
        go_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    references = backend.find_references(tmp_path, "RawNode.Ready")
    assert any("rn.Ready()" in item and "receiver not proven" in item for item in references)
