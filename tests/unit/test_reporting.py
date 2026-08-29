import json
from pathlib import Path

from consensus_seam.models import CapabilityReport, InterfaceReport, ReviewReport
from consensus_seam.reporting import ArtifactStore
from tests.helpers import capability_report, review_report


def test_publish_latest_tracks_audit_files_but_excludes_worktree(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    first = ArtifactStore.create(runs)
    first.write_json("run-config.json", {"project": "mini-raft"})
    first.write_json("capability-report.json", {"target": "first"})
    first.write_text("changes.patch", "first patch\n")
    first.write_json(
        "workflow-result.json",
        {
            "outcome": "PASS",
            "run_directory": str(first.run_directory),
            "reason": None,
        },
    )
    first.write_json("logs/build.json", {"passed": True})
    worktree = first.run_directory / "patched-worktree"
    worktree.mkdir()
    (worktree / "generated.go").write_text("package generated\n", encoding="utf-8")
    repair_candidate = first.run_directory / "repair-candidate"
    repair_candidate.mkdir()
    (repair_candidate / "generated.go").write_text(
        "package generated\n", encoding="utf-8"
    )
    repaired = first.run_directory / "repaired-worktree-p1"
    repaired.mkdir()
    (repaired / "generated.go").write_text("package generated\n", encoding="utf-8")

    latest = first.publish_latest()
    assert (latest / "capability-report.json").is_file()
    assert (latest / "logs/build.json").is_file()
    assert (latest / "APPLY.md").is_file()
    assert not (latest / "patched-worktree").exists()
    assert not (latest / "repair-candidate").exists()
    assert not (latest / "repaired-worktree-p1").exists()
    assert latest == runs / "latest" / "mini-raft"

    second = ArtifactStore.create(runs)
    second.write_json("run-config.json", {"project": "mini-raft"})
    second.write_json("capability-report.json", {"target": "second"})
    second.publish_latest()
    assert '"second"' in (latest / "capability-report.json").read_text()
    assert not (latest / "changes.patch").exists()
    assert "没有可应用的已通过候选" in (latest / "APPLY.md").read_text(
        encoding="utf-8"
    )

    other = ArtifactStore.create(runs)
    other.write_json("run-config.json", {"project": "etcd-raft"})
    other.write_json("capability-report.json", {"target": "other"})
    other_latest = other.publish_latest()
    assert other_latest == runs / "latest" / "etcd-raft"
    assert '"other"' in (other_latest / "capability-report.json").read_text()
    assert '"second"' in (latest / "capability-report.json").read_text()


def test_incomplete_run_marks_stage_reports_without_publishing(tmp_path: Path) -> None:
    artifacts = ArtifactStore.create(tmp_path / "runs")
    artifacts.write_text("USAGE.md", "# candidate\n\nstage output\n")
    artifacts.write_text("AUDIT.md", "# audit\n\nstage evidence\n")

    failure = artifacts.mark_incomplete("AgentRuntimeError")

    usage = (artifacts.run_directory / "USAGE.md").read_text(encoding="utf-8")
    audit = (artifacts.run_directory / "AUDIT.md").read_text(encoding="utf-8")
    assert "本次运行未完成" in usage
    assert "不得作为最终使用说明" in usage
    assert "本次运行未完成" in audit
    assert json.loads(failure.read_text(encoding="utf-8")) == {
        "error_type": "AgentRuntimeError",
        "outcome": "INCOMPLETE",
    }


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
                "instance_reference": "Pending 返回稳定 handle 与消息快照。",
                "target_binding_strategy": "控制器根据缓存目标解析真实节点。",
                "cache_effects": "成功后删除；同步失败时保留。",
                "covered_paths": ["RawNode synchronous ingress"],
                "uncovered_paths": ["Node asynchronous ingress：目标入口不返回处理结果"],
                "notes": ["先创建测试控制器，再按 MessageHandle 调用注入入口。"],
                "usage_examples": [
                    "pending := controller.Pending()\n"
                    "chosen := pending[0]\n"
                    "err := controller.Inject(chosen.Handle)"
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
    assert "消息控制调用顺序" in content
    assert "将同一 Handle 交给 Drop 或 Inject" in content
    assert "Node.Status" in content
    assert "InjectForTest" in content
    assert "ClearPendingForTest" in content
    assert "进程内测试路径" in content
    assert "缓存实例引用" in content
    assert "Pending 返回稳定 handle" in content
    assert "目标绑定方式" in content
    assert "缓存变化与失败语义" in content
    assert "err := node.Step(ctx, msg)" in content
    assert "controller.Inject(chosen.Handle)" in content
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
