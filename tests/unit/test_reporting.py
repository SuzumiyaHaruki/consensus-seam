from pathlib import Path

from consensus_seam.reporting import ArtifactStore


def test_publish_latest_tracks_audit_files_but_excludes_worktree(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    first = ArtifactStore.create(runs)
    first.write_json("capability-report.json", {"target": "first"})
    first.write_text("changes.patch", "first patch\n")
    first.write_json("logs/build.json", {"passed": True})
    worktree = first.run_directory / "patched-worktree"
    worktree.mkdir()
    (worktree / "generated.go").write_text("package generated\n", encoding="utf-8")

    latest = first.publish_latest()
    assert (latest / "capability-report.json").is_file()
    assert (latest / "logs/build.json").is_file()
    assert (latest / "APPLY.md").is_file()
    assert not (latest / "patched-worktree").exists()

    second = ArtifactStore.create(runs)
    second.write_json("capability-report.json", {"target": "second"})
    second.publish_latest()
    assert '"second"' in (latest / "capability-report.json").read_text()
    assert not (latest / "changes.patch").exists()
