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
        "message_cache_injection_coherence",
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

    def test_support_fields(name: str, direct_reason: str) -> dict[str, Any]:
        patchable_status = statuses[name] == "PATCHABLE"
        return {
            "existing_test_interface_complete": statuses[name] == "SUPPORTED",
            "test_support_reason": (
                f"{name} requires additional test support"
                if patchable_status
                else direct_reason
            ),
            "suggested_changes": (
                [f"expose {name} with a low-intrusion test hook or wrapper"]
                if patchable_status
                else []
            ),
        }

    return {
        "target": "mini-raft",
        "capabilities": {
            "message_capture": {
                "status": statuses["message_capture"],
                "evidence": evidence("Transport.Send"),
                "boundary": "application_transport",
                **test_support_fields("message_capture", "existing controller is directly usable"),
            },
            "message_injection": {
                "status": statuses["message_injection"],
                "evidence": evidence("Node.Step"),
                "boundary": "protocol_handler",
                "gap": "stable ID lookup is missing" if patchable == "message_injection" else None,
                **test_support_fields("message_injection", "existing injection API is directly usable"),
            },
            "time_control": {
                "status": statuses["time_control"],
                "evidence": evidence("Node.Tick"),
                "boundary": "protocol_logical_time",
                **test_support_fields("time_control", "Node.Tick is directly usable"),
            },
            "randomness_control": {
                "status": statuses["randomness_control"],
                "reason": "random source and protocol state are entangled",
                "existing_test_interface_complete": False,
                "test_support_reason": "existing random control is incomplete and invasive",
                **(
                    test_support_fields("randomness_control", "existing random control is directly usable")
                    if statuses["randomness_control"] == "PATCHABLE"
                    else {}
                ),
            },
            "lifecycle_control": {
                "status": statuses["lifecycle_control"],
                "reason": "the implementation does not define restart state ownership",
                "existing_test_interface_complete": False,
                "test_support_reason": "existing lifecycle control is incomplete and invasive",
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
                **test_support_fields("observation", "Node.Status is directly usable"),
            },
            "external_input": {
                "status": statuses["external_input"],
                "evidence": evidence("Node.Propose"),
                "entrypoints": ["Node.Propose"],
                **test_support_fields("external_input", "Node.Propose is directly usable"),
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
