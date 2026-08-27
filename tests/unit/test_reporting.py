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
    report_payload["capabilities"]["message_injection"]["usage_examples"] = [
        "err := node.Step(ctx, msg)"
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
                "public_entrypoints": [
                    {
                        "file": "injection_seam.go",
                        "symbol": "InjectForTest",
                    },
                    {
                        "file": "injection_seam.go",
                        "symbol": "ClearPendingForTest",
                    },
                ],
                "implementation_approach": [
                    "通过 hook 捕获消息。",
                    "使用控制对象按 ID 保存并选择消息。",
                ],
                "test_mode": "进程内测试路径",
                "covered_paths": ["RawNode synchronous ingress"],
                "uncovered_paths": ["Node asynchronous ingress：目标入口不返回处理结果"],
                "notes": ["先创建测试控制器，再按消息 ID 调用注入入口。"],
                "usage_examples": [
                    "pending := controller.Pending()\nerr := controller.Inject(pending[0])"
                ],
            }
        }
    )

    review_payload = review_report()
    review_payload["risks"] = ["The remaining setup cost does not invalidate the interface."]
    review = ReviewReport.model_validate(review_payload)
    path = artifacts.write_usage(report, interface, review)
    content = path.read_text(encoding="utf-8")
    audit = (artifacts.run_directory / "AUDIT.md").read_text(encoding="utf-8")

    assert "快速接口矩阵" in content
    assert "Node.Status" in content
    assert "InjectForTest" in content
    assert "ClearPendingForTest" in content
    assert "进程内测试路径" in content
    assert "err := node.Step(ctx, msg)" in content
    assert "controller.Inject(pending[0])" in content
    assert "Node asynchronous ingress" in content
    assert "Reviewer 最终结论" in content
    assert "非阻塞剩余风险" in content
    assert "The remaining setup cost" in content
    assert "Analyzer 建议（修改前）" not in content
    assert "通过 hook 捕获消息" not in content

    assert "测试接口审计报告" in audit
    assert "Analyzer 建议（修改前）" in audit
    assert "实际实现方式" in audit
    assert "通过 hook 捕获消息" in audit
    assert "修改前已知限制（供对照）" in audit
