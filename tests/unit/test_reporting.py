from pathlib import Path

from consensus_seam.models import CapabilityReport, InterfaceReport, ReviewReport
from consensus_seam.reporting import ArtifactStore
from tests.helpers import capability_report, review_report


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
    assert "应用最近一次已验证补丁" in (latest / "APPLY.md").read_text(
        encoding="utf-8"
    )


def test_usage_report_covers_existing_and_generated_interfaces(tmp_path: Path) -> None:
    artifacts = ArtifactStore.create(tmp_path / "runs")
    report_payload = capability_report()
    report_payload["capabilities"]["message_injection"]["execution_paths"] = [
        "Node asynchronous ingress",
        "RawNode synchronous ingress",
    ]
    report_payload["capabilities"]["message_injection"]["limitations"] = [
        "This limitation describes the target before transformation."
    ]
    report = CapabilityReport.model_validate(report_payload)
    interface = InterfaceReport.model_validate(
        {
            "message_injection": {
                "implemented": True,
                "message_id_scope": "test_session",
                "entrypoint": {
                    "file": "injection_seam.go",
                    "symbol": "InjectForTest",
                },
                "implementation_approach": [
                    "通过 hook 捕获消息。",
                    "使用控制对象按 ID 保存并选择消息。",
                ],
                "test_mode": "进程内测试路径",
                "covered_paths": ["RawNode synchronous ingress"],
                "uncovered_paths": ["Node asynchronous ingress：目标入口不返回处理结果"],
                "notes": ["先创建测试控制器，再按消息 ID 调用注入入口。"],
            }
        }
    )

    review_payload = review_report()
    review_payload["risks"] = ["The remaining setup cost does not invalidate the interface."]
    review = ReviewReport.model_validate(review_payload)
    path = artifacts.write_usage(report, interface, review)
    content = path.read_text(encoding="utf-8")

    assert "Node.Status" in content
    assert "InjectForTest" in content
    assert "通过 hook 捕获消息" in content
    assert "按 ID 保存并选择消息" in content
    assert "进程内测试路径" in content
    assert "修改前测试接口是否完整：否" in content
    assert "Analyzer 建议（修改前）" in content
    assert "实际实现方式" in content
    assert "Node asynchronous ingress" in content
    assert "RawNode synchronous ingress" in content
    assert "未覆盖路径" in content
    assert "独立 Reviewer 结论" in content
    assert "非阻塞剩余风险" in content
    assert "The remaining setup cost" in content
    injection_section = content.split("\n## 消息注入\n", 1)[1].split(
        "\n## 时间控制\n", 1
    )[0]
    assert "当前缺口" not in injection_section
    assert "修改前已知限制（供对照）" in injection_section
    assert "### 当前限制" not in injection_section
