"""Project-specific deterministic capability check descriptor."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import FailureCode


@dataclass(frozen=True)
class CapabilityCheck:
    name: str
    capability: str
    command: str
    failure_code: FailureCode
