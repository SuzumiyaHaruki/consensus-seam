import os
import shutil
import subprocess
from pathlib import Path

from consensus_seam.config import load_project
from consensus_seam.verify.fixtures import materialized_fixtures


def test_hidden_fixture_is_not_agent_visible_and_is_removed_after_use(
    tmp_path: Path,
) -> None:
    project = load_project(
        Path(__file__).resolve().parents[2] / "evaluation/mini-raft/project.yaml"
    )
    agent_view = project.agent_manifest()
    assert "capability_checks" not in agent_view
    assert "verification_fixtures" not in agent_view
    assert "experiment" not in agent_view
    assert project.verification_fixtures[0].source.is_file()
    assert [check.name for check in project.manifest.capability_checks] == [
        "MC1 基本消息捕获",
        "MC2 捕获后停止自动发送",
        "MC3 精确消息注入",
        "MC4 Mini Raft 失败投递保留",
    ]
    try:
        project.verification_fixtures[0].source.relative_to(project.repository)
    except ValueError:
        pass
    else:
        raise AssertionError("hidden fixture is inside Agent-visible repository")

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    destination = worktree / project.verification_fixtures[0].destination
    with materialized_fixtures(project.verification_fixtures, worktree):
        assert destination.is_file()
    assert not destination.exists()


def test_hidden_mini_raft_contract_accepts_an_internal_type_with_thin_api(
    tmp_path: Path,
) -> None:
    project = load_project(
        Path(__file__).resolve().parents[2] / "evaluation/mini-raft/project.yaml"
    )
    worktree = tmp_path / "mini-raft"
    shutil.copytree(project.repository, worktree, ignore=shutil.ignore_patterns(".git"))
    (worktree / "message_controller.go").write_text(
        """package miniraft

import (
    "errors"
    "strconv"
    "sync"
)

var errUnknownMessage = errors.New("unknown pending message")

type messageMeta struct {
    ID string
    CaptureSequence uint64
    Message
}

type messageController struct {
    mu sync.Mutex
    wrapped Transport
    pending []messageMeta
    sequence uint64
}

func NewMessageController(wrapped Transport) *messageController {
    return &messageController{wrapped: wrapped}
}

func (controller *messageController) Send(message Message) error {
    controller.mu.Lock()
    defer controller.mu.Unlock()
    controller.sequence++
    controller.pending = append(controller.pending, messageMeta{
        ID: strconv.FormatUint(controller.sequence, 10),
        CaptureSequence: controller.sequence,
        Message: message.Clone(),
    })
    return nil
}

func (controller *messageController) ListPending() []messageMeta {
    controller.mu.Lock()
    defer controller.mu.Unlock()
    result := make([]messageMeta, len(controller.pending))
    copy(result, controller.pending)
    return result
}

func (controller *messageController) ClearPending() {
    controller.mu.Lock()
    defer controller.mu.Unlock()
    controller.pending = nil
}

func (controller *messageController) Inject(id string) error {
    controller.mu.Lock()
    var snapshot Message
    found := false
    for _, pending := range controller.pending {
        if pending.ID == id {
            snapshot = pending.Message.Clone()
            found = true
            break
        }
    }
    controller.mu.Unlock()
    if !found { return errUnknownMessage }
    if err := controller.wrapped.Send(snapshot); err != nil { return err }
    controller.mu.Lock()
    defer controller.mu.Unlock()
    for index, pending := range controller.pending {
        if pending.ID == id {
            controller.pending = append(controller.pending[:index], controller.pending[index+1:]...)
            break
        }
    }
    return nil
}
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["GOCACHE"] = str(tmp_path / "gocache")
    with materialized_fixtures(project.verification_fixtures, worktree):
        completed = subprocess.run(
            ["go", "test", "./_consensus_seam_hidden/acceptance"],
            cwd=worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr
