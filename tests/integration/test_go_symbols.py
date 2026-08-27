from __future__ import annotations

from pathlib import Path

from consensus_seam.languages.go import GoBackend


def test_go_ast_finds_pointer_receiver_method(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("GOCACHE", str(tmp_path / "gocache"))  # type: ignore[attr-defined]
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
    references = backend.find_references(tmp_path, "RawNode.Ready")
    assert any("rn.Ready()" in item and "receiver not proven" in item for item in references)
