from __future__ import annotations

from typing import Any


def evidence(symbol: str) -> list[dict[str, Any]]:
    return [{"symbol": symbol, "reason": f"actual code evidence at {symbol}"}]


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
            },
            "observation": {
                "status": statuses["observation"],
                "evidence": evidence("Node.Status"),
            },
            "external_input": {
                "status": statuses["external_input"],
                "evidence": evidence("Node.Propose"),
                "entrypoints": ["Node.Propose"],
            },
        },
    }
