"""Validated data contracts shared by the controller and all Agents."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CAPABILITY_NAMES = frozenset(
    {
        "message_capture",
        "message_injection",
        "time_control",
        "randomness_control",
        "lifecycle_control",
        "observation",
        "external_input",
    }
)


class StrictModel(BaseModel):
    """Base model that rejects silently invented fields."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CommandConfig(StrictModel):
    command: str = Field(min_length=1)


class WorkflowLimits(StrictModel):
    agent1_reanalysis_rounds: int = Field(default=2, ge=1, le=10)
    agent2_patch_rounds: int = Field(default=3, ge=1, le=10)


class ProjectManifest(StrictModel):
    name: str = Field(min_length=1)
    language: Literal["go"]
    protocol: str = Field(min_length=1)
    repository: Path
    build: CommandConfig
    test: CommandConfig
    working_directory: Path = Path(".")
    limits: WorkflowLimits = Field(default_factory=WorkflowLimits)


class CapabilityDefinition(StrictModel):
    description: str = Field(min_length=1)
    accepted_v0_forms: list[str] = Field(default_factory=list)


class CapabilityPrerequisites(StrictModel):
    target_language: dict[str, list[str]] = Field(default_factory=dict)


class CapabilitySpec(StrictModel):
    version: int = Field(ge=1)
    capabilities: dict[str, CapabilityDefinition]
    prerequisites: CapabilityPrerequisites | dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_v0_capabilities(self) -> "CapabilitySpec":
        missing = CAPABILITY_NAMES - self.capabilities.keys()
        if missing:
            raise ValueError(f"capability spec is missing: {', '.join(sorted(missing))}")
        return self


class ModificationPolicy(StrictModel):
    allowed: list[str]
    forbidden: list[str]


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PATCHABLE = "PATCHABLE"
    PARTIAL = "PARTIAL"
    INVASIVE = "INVASIVE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CodeEvidence(StrictModel):
    file: str | None = None
    symbol: str | None = None
    line: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_location(self) -> "CodeEvidence":
        if self.file is None and self.symbol is None:
            raise ValueError("evidence must identify a file or symbol")
        return self


class CapabilityFinding(StrictModel):
    status: CapabilityStatus
    evidence: list[CodeEvidence] = Field(default_factory=list)
    boundary: str | None = None
    gap: str | None = None
    reason: str | None = None
    limitations: list[str] = Field(default_factory=list)
    suggested_direction: str | None = None
    entrypoints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_supporting_explanation(self) -> "CapabilityFinding":
        if self.status in {
            CapabilityStatus.SUPPORTED,
            CapabilityStatus.PATCHABLE,
            CapabilityStatus.PARTIAL,
        } and not self.evidence:
            raise ValueError(f"{self.status.value} requires code evidence")
        if self.status in {
            CapabilityStatus.INVASIVE,
            CapabilityStatus.UNKNOWN,
        } and not (self.reason or self.gap or self.evidence):
            raise ValueError(f"{self.status.value} requires a reason, gap, or evidence")
        return self


class CapabilityReport(StrictModel):
    target: str = Field(min_length=1)
    capabilities: dict[str, CapabilityFinding]

    required_capabilities: ClassVar[frozenset[str]] = CAPABILITY_NAMES

    @model_validator(mode="after")
    def require_exact_v0_capabilities(self) -> "CapabilityReport":
        names = set(self.capabilities)
        missing = self.required_capabilities - names
        extra = names - self.required_capabilities
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing: {', '.join(sorted(missing))}")
            if extra:
                details.append(f"unexpected: {', '.join(sorted(extra))}")
            raise ValueError("invalid capability set (" + "; ".join(details) + ")")
        if self.capabilities["external_input"].status is CapabilityStatus.PATCHABLE:
            raise ValueError("external_input is discovery-only and cannot be PATCHABLE in v0.1")
        return self

    def patchable(self) -> set[str]:
        return {
            name
            for name, finding in self.capabilities.items()
            if finding.status is CapabilityStatus.PATCHABLE
        }

    def apply_rediscovered(self, names: set[str]) -> None:
        for name in names:
            if name not in self.capabilities:
                raise ValueError(f"unknown rediscovered capability: {name}")
            finding = self.capabilities[name]
            finding.status = CapabilityStatus.INVASIVE
            finding.reason = "Transformer rediscovered that the change is invasive"


class CodeLocation(StrictModel):
    file: str | None = None
    symbol: str | None = None
    meaning: str | None = None

    @model_validator(mode="after")
    def require_file_or_symbol(self) -> "CodeLocation":
        if self.file is None and self.symbol is None:
            raise ValueError("location must identify a file or symbol")
        return self


class InterfaceCapability(StrictModel):
    implemented: bool
    rediscovered_status: Literal["INVASIVE_REDISCOVERED"] | None = None
    capture_boundary: CodeLocation | None = None
    pending_store: CodeLocation | None = None
    entrypoint: CodeLocation | None = None
    copy_strategy: str | None = None
    production_mode: str | None = None
    test_mode: str | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> "InterfaceCapability":
        if self.implemented and self.rediscovered_status is not None:
            raise ValueError("an implemented capability cannot be rediscovered as invasive")
        if not self.implemented and self.rediscovered_status is None:
            raise ValueError("an unimplemented PATCHABLE capability needs rediscovered_status")
        return self


class InterfaceReport(StrictModel):
    message_capture: InterfaceCapability | None = None
    message_injection: InterfaceCapability | None = None
    time_control: InterfaceCapability | None = None
    randomness_control: InterfaceCapability | None = None
    lifecycle_control: InterfaceCapability | None = None
    observation: InterfaceCapability | None = None

    @model_validator(mode="after")
    def require_one_capability(self) -> "InterfaceReport":
        if not self.capabilities():
            raise ValueError("interface report must describe at least one capability")
        return self

    def capabilities(self) -> dict[str, InterfaceCapability]:
        return {
            name: value
            for name in CAPABILITY_NAMES - {"external_input"}
            if (value := getattr(self, name, None)) is not None
        }

    def rediscovered(self) -> set[str]:
        return {
            name
            for name, value in self.capabilities().items()
            if value.rediscovered_status == "INVASIVE_REDISCOVERED"
        }


class ReviewOverall(str, Enum):
    PASS = "PASS"
    REVISE_AGENT1 = "REVISE_AGENT1"
    REVISE_AGENT2 = "REVISE_AGENT2"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class ReviewIssue(StrictModel):
    capability: str | None = None
    file: str | None = None
    symbol: str | None = None
    reason: str = Field(min_length=1)


class ReviewReport(StrictModel):
    overall: ReviewOverall
    issues: list[ReviewIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_consistent_issues(self) -> "ReviewReport":
        if self.overall is ReviewOverall.PASS and self.issues:
            raise ValueError("PASS review cannot contain issues")
        if self.overall is not ReviewOverall.PASS and not self.issues:
            raise ValueError(f"{self.overall.value} review must explain at least one issue")
        return self


class FailureCode(str, Enum):
    BASELINE_FAILED = "BASELINE_FAILED"
    BUILD_FAILED = "BUILD_FAILED"
    MESSAGE_CAPTURE_FAILED = "MESSAGE_CAPTURE_FAILED"
    MESSAGE_SUPPRESSION_FAILED = "MESSAGE_SUPPRESSION_FAILED"
    MESSAGE_INJECTION_FAILED = "MESSAGE_INJECTION_FAILED"
    MESSAGE_BYPASS_SUSPECTED = "MESSAGE_BYPASS_SUSPECTED"
    TIME_CONTROL_FAILED = "TIME_CONTROL_FAILED"
    RANDOMNESS_CONTROL_FAILED = "RANDOMNESS_CONTROL_FAILED"
    LIFECYCLE_CONTROL_FAILED = "LIFECYCLE_CONTROL_FAILED"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"
    REGRESSION_FAILED = "REGRESSION_FAILED"
    SEMANTIC_AMBIGUITY = "SEMANTIC_AMBIGUITY"


class FailureRoute(str, Enum):
    AGENT1 = "AGENT1"
    AGENT2 = "AGENT2"
    AGENT3 = "AGENT3"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    NONE = "NONE"


class CommandExecution(StrictModel):
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = Field(ge=0)

    @property
    def passed(self) -> bool:
        return self.returncode == 0


class BaselineReport(StrictModel):
    passed: bool
    build: CommandExecution
    tests: CommandExecution | None = None
    failure_code: FailureCode | None = None


class VerificationReport(StrictModel):
    passed: bool
    build: CommandExecution
    existing_tests: CommandExecution | None = None
    capability_tests: list[CommandExecution] = Field(default_factory=list)
    failure_code: FailureCode | None = None
    route: FailureRoute = FailureRoute.NONE
    details: list[str] = Field(default_factory=list)


class WorkflowOutcome(str, Enum):
    ANALYZED = "ANALYZED"
    NO_PATCH_NEEDED = "NO_PATCH_NEEDED"
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class WorkflowResult(StrictModel):
    outcome: WorkflowOutcome
    run_directory: Path
    reason: str | None = None
