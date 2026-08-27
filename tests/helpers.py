from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any


def write_project_manifest(
    directory: Path,
    repository: Path,
    *,
    command: str = "go test ./...",
    extra: Iterable[str] = (),
) -> Path:
    manifest = directory / "project.yaml"
    lines = [
        "name: mini-raft",
        "language: go",
        "protocol: raft",
        f"repository: {repository}",
        "system_boundary:",
        "  kind: protocol_library",
        "  description: Mini Raft protocol core only",
        *extra,
        f"build: {{command: '{command}'}}",
        f"test: {{command: '{command}'}}",
    ]
    manifest.write_text("\n".join(lines), encoding="utf-8")
    return manifest


def evidence(symbol: str) -> list[dict[str, Any]]:
    return [{"symbol": symbol, "reason": f"actual code evidence at {symbol}"}]


def obligation(status: str, symbol: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "evidence": evidence(symbol) if status == "SATISFIED" else [],
        "reason": reason,
    }


def review_report() -> dict[str, Any]:
    checks = []
    for name in (
        "original_send_suppressed",
        "protocol_logic_unchanged",
        "exact_target_preserved",
        "existing_tests_unchanged",
        "testing_contract_conformance",
    ):
        checks.append(
            {
                "name": name,
                "result": "PASS",
                "evidence": evidence("verified.diff"),
                "reason": f"test evidence for {name}",
            }
        )
    return {"overall": "PASS", "checks": checks, "issues": [], "risks": []}


def capability_report(*, patchable: str | None = "message_injection") -> dict[str, Any]:
    statuses = {
        "message_capture": "SUPPORTED",
        "message_injection": "SUPPORTED",
        "time_control": "SUPPORTED",
        "randomness_control": "INVASIVE",
        "lifecycle_control": "INVASIVE",
        "observation": "SUPPORTED",
        "external_input": "SUPPORTED",
    }
    if patchable is not None:
        statuses[patchable] = "PATCHABLE"
    return {
        "target": "mini-raft",
        "capabilities": {
            "message_capture": {
                "status": statuses["message_capture"],
                "evidence": evidence("Transport.Send"),
                "boundary": "application_transport",
            },
            "message_injection": {
                "status": statuses["message_injection"],
                "evidence": evidence("Node.Step"),
                "boundary": "protocol_handler",
                "gap": "stable ID lookup is missing" if patchable == "message_injection" else None,
            },
            "time_control": {
                "status": statuses["time_control"],
                "evidence": evidence("Node.Tick"),
                "boundary": "protocol_logical_time",
            },
            "randomness_control": {
                "status": statuses["randomness_control"],
                "reason": "random source and protocol state are entangled",
            },
            "lifecycle_control": {
                "status": statuses["lifecycle_control"],
                "reason": "the implementation does not define restart state ownership",
                "obligations": {
                    "stop_boundary": obligation(
                        "SATISFIED", "Node.Pause", "scheduler pause exists"
                    ),
                    "restart_or_recovery_boundary": obligation(
                        "MISSING", "Node.Resume", "resume is not recovery"
                    ),
                    "state_ownership_defined": obligation(
                        "MISSING", "Node", "recoverable ownership is undefined"
                    ),
                    "persistent_volatile_semantics_defined": obligation(
                        "MISSING", "Node", "persistent split is undefined"
                    ),
                },
            },
            "observation": {
                "status": statuses["observation"],
                "evidence": evidence("Node.Status"),
            },
            "external_input": {
                "status": statuses["external_input"],
                "evidence": evidence("Node.Propose"),
                "entrypoints": ["Node.Propose"],
                "obligations": {
                    "workload_entrypoint": obligation(
                        "SATISFIED", "Node.Propose", "proposal is application work"
                    ),
                    "protocol_ingress_excluded": obligation(
                        "SATISFIED", "Node.Step", "Step is explicitly excluded"
                    ),
                    "timer_and_internal_events_excluded": obligation(
                        "SATISFIED", "Node.Tick", "Tick is explicitly excluded"
                    ),
                },
            },
        },
    }
