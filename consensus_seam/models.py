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


class FailureCode(str, Enum):
    BASELINE_FAILED = "BASELINE_FAILED"
    BUILD_FAILED = "BUILD_FAILED"
    MESSAGE_CAPTURE_FAILED = "MESSAGE_CAPTURE_FAILED"
    MESSAGE_SUPPRESSION_FAILED = "MESSAGE_SUPPRESSION_FAILED"
    MESSAGE_INJECTION_FAILED = "MESSAGE_INJECTION_FAILED"
    # Reserved for a future deterministic bypass detector. Manifest capability
    # checks cannot emit this code in v0.1.
    MESSAGE_BYPASS_SUSPECTED = "MESSAGE_BYPASS_SUSPECTED"
    TIME_CONTROL_FAILED = "TIME_CONTROL_FAILED"
    RANDOMNESS_CONTROL_FAILED = "RANDOMNESS_CONTROL_FAILED"
    LIFECYCLE_CONTROL_FAILED = "LIFECYCLE_CONTROL_FAILED"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"
    REGRESSION_FAILED = "REGRESSION_FAILED"
    SEMANTIC_AMBIGUITY = "SEMANTIC_AMBIGUITY"


class SystemBoundary(StrictModel):
    kind: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ExperimentConfig(StrictModel):
    kind: Literal["engineering_smoke", "blind_capability", "repair"]
    oracle_visible_to_agents: bool
    research_claim: str = Field(min_length=1)


class AgentModelConfig(StrictModel):
    model: str = Field(min_length=1)
    thinking: Literal["enabled", "disabled"] = "enabled"
    reasoning_effort: Literal["low", "high", "max"] = "high"
    max_tokens: int = Field(default=32768, ge=1024, le=384000)


class LLMConfig(StrictModel):
    analyzer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(
            model="deepseek-v4-flash", reasoning_effort="max"
        )
    )
    transformer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(
            model="deepseek-v4-flash", reasoning_effort="max"
        )
    )
    reviewer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(
            model="deepseek-v4-pro", reasoning_effort="high"
        )
    )


class CapabilityCheckConfig(StrictModel):
    name: str = Field(min_length=1)
    capability: Literal[
        "message_capture",
        "message_injection",
        "time_control",
        "randomness_control",
        "lifecycle_control",
        "observation",
    ]
    command: str = Field(min_length=1)
    failure_code: FailureCode


class VerificationFixtureConfig(StrictModel):
    source: Path
    destination: Path

    @model_validator(mode="after")
    def destination_must_be_relative(self) -> "VerificationFixtureConfig":
        if self.destination.is_absolute() or ".." in self.destination.parts:
            raise ValueError("verification fixture destination must stay in the worktree")
        if ".git" in self.destination.parts:
            raise ValueError("verification fixture cannot target .git")
        return self


TransformCapability = Literal[
    "message_capture",
    "message_injection",
    "time_control",
    "randomness_control",
    "lifecycle_control",
    "observation",
]


class WorkflowLimits(StrictModel):
    agent1_reanalysis_rounds: int = Field(default=2, ge=1, le=10)
    agent2_patch_rounds: int = Field(default=3, ge=1, le=10)


class ProjectManifest(StrictModel):
    name: str = Field(min_length=1)
    language: Literal["go"]
    protocol: str = Field(min_length=1)
    repository: Path
    system_boundary: SystemBoundary
    experiment: ExperimentConfig | None = None
    build: CommandConfig
    test: CommandConfig
    working_directory: Path = Path(".")
    transform_capabilities: list[TransformCapability] | None = None
    capability_checks: list[CapabilityCheckConfig] = Field(default_factory=list)
    verification_fixtures: list[VerificationFixtureConfig] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    limits: WorkflowLimits = Field(default_factory=WorkflowLimits)

    @model_validator(mode="after")
    def validate_capability_checks(self) -> "ProjectManifest":
        if self.transform_capabilities is not None:
            if not self.transform_capabilities:
                raise ValueError("transform_capabilities cannot be empty")
            if len(self.transform_capabilities) != len(set(self.transform_capabilities)):
                raise ValueError("transform_capabilities must be unique")
        names = [check.name for check in self.capability_checks]
        if len(names) != len(set(names)):
            raise ValueError("capability check names must be unique")
        allowed_codes = {
            "message_capture": {
                FailureCode.MESSAGE_CAPTURE_FAILED,
                FailureCode.MESSAGE_SUPPRESSION_FAILED,
            },
            "message_injection": {FailureCode.MESSAGE_INJECTION_FAILED},
            "time_control": {FailureCode.TIME_CONTROL_FAILED},
            "randomness_control": {FailureCode.RANDOMNESS_CONTROL_FAILED},
            "lifecycle_control": {FailureCode.LIFECYCLE_CONTROL_FAILED},
            "observation": {FailureCode.OBSERVATION_FAILED},
        }
        for check in self.capability_checks:
            if check.failure_code not in allowed_codes[check.capability]:
                raise ValueError(
                    f"{check.failure_code.value} is not valid for {check.capability}"
                )
        return self


class CapabilityDefinition(StrictModel):
    description: str = Field(min_length=1)
    accepted_v0_forms: list[str] = Field(default_factory=list)
    obligations: dict[str, str] = Field(default_factory=dict)
    testing_contract: dict[str, str] = Field(default_factory=dict)


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


class ObligationStatus(str, Enum):
    SATISFIED = "SATISFIED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ObligationAssessment(StrictModel):
    status: ObligationStatus
    evidence: list[CodeEvidence] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def satisfied_requires_evidence(self) -> "ObligationAssessment":
        if self.status is ObligationStatus.SATISFIED and not self.evidence:
            raise ValueError("SATISFIED obligation requires code evidence")
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
    obligations: dict[str, "ObligationAssessment"] = Field(default_factory=dict)

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
        self._validate_lifecycle_obligations()
        self._validate_external_input_obligations()
        return self

    def _validate_lifecycle_obligations(self) -> None:
        finding = self.capabilities["lifecycle_control"]
        required = {
            "stop_boundary",
            "restart_or_recovery_boundary",
            "state_ownership_defined",
            "persistent_volatile_semantics_defined",
        }
        if set(finding.obligations) != required:
            raise ValueError("lifecycle_control must report all lifecycle obligations")
        states = {name: finding.obligations[name].status for name in required}
        if finding.status is CapabilityStatus.SUPPORTED and any(
            state is not ObligationStatus.SATISFIED for state in states.values()
        ):
            raise ValueError("SUPPORTED lifecycle_control requires every obligation SATISFIED")
        recovery_missing = (
            states["restart_or_recovery_boundary"] is ObligationStatus.MISSING
        )
        semantics_missing = any(
            states[name] is ObligationStatus.MISSING
            for name in {
                "state_ownership_defined",
                "persistent_volatile_semantics_defined",
            }
        )
        if recovery_missing and semantics_missing and finding.status is not CapabilityStatus.INVASIVE:
            raise ValueError(
                "missing recovery and state semantics require lifecycle_control INVASIVE"
            )

    def _validate_external_input_obligations(self) -> None:
        finding = self.capabilities["external_input"]
        required = {
            "workload_entrypoint",
            "protocol_ingress_excluded",
            "timer_and_internal_events_excluded",
        }
        if set(finding.obligations) != required:
            raise ValueError("external_input must report all external-input obligations")
        if finding.status is CapabilityStatus.SUPPORTED and any(
            finding.obligations[name].status is not ObligationStatus.SATISFIED
            for name in required
        ):
            raise ValueError("SUPPORTED external_input requires every obligation SATISFIED")

    def patchable(self, allowlist: list[str] | set[str] | None = None) -> set[str]:
        result = {
            name
            for name, finding in self.capabilities.items()
            if finding.status is CapabilityStatus.PATCHABLE
        }
        return result if allowlist is None else result & set(allowlist)

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
    message_id_scope: Literal[
        "pending_store_instance", "test_session", "node", "global"
    ] | None = None
    controller_operations: Literal["serialized"] | None = None
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
        for name in ("message_capture", "message_injection"):
            capability = getattr(self, name)
            if capability is None or not capability.implemented:
                continue
            if capability.message_id_scope is None:
                raise ValueError(f"implemented {name} must declare message_id_scope")
            if capability.controller_operations != "serialized":
                raise ValueError(
                    f"implemented {name} must declare serialized controller operations"
                )
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


class ReviewCheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReviewCheck(StrictModel):
    name: str = Field(min_length=1)
    result: ReviewCheckResult
    evidence: list[CodeEvidence] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def pass_requires_evidence(self) -> "ReviewCheck":
        if self.result is ReviewCheckResult.PASS and not self.evidence:
            raise ValueError("PASS review check requires evidence")
        return self


class ReviewReport(StrictModel):
    overall: ReviewOverall
    checks: list[ReviewCheck]
    issues: list[ReviewIssue] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    required_checks: ClassVar[frozenset[str]] = frozenset(
        {
            "original_send_suppressed",
            "protocol_logic_unchanged",
            "message_snapshot_stable",
            "exact_target_preserved",
            "failed_injection_preserves_pending",
            "existing_tests_unchanged",
        }
    )

    @model_validator(mode="after")
    def require_consistent_issues(self) -> "ReviewReport":
        names = [check.name for check in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("review check names must be unique")
        missing = self.required_checks - set(names)
        if missing:
            raise ValueError(f"review report is missing checks: {', '.join(sorted(missing))}")
        if self.overall is ReviewOverall.PASS and self.issues:
            raise ValueError("PASS review cannot contain issues")
        if self.overall is ReviewOverall.PASS and any(
            check.result not in {
                ReviewCheckResult.PASS,
                ReviewCheckResult.NOT_APPLICABLE,
            }
            for check in self.checks
        ):
            raise ValueError("PASS review cannot contain failed or unknown checks")
        if self.overall is not ReviewOverall.PASS and not self.issues:
            raise ValueError(f"{self.overall.value} review must explain at least one issue")
        return self


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


class PatchMetrics(StrictModel):
    existing_production_files_modified: list[str] = Field(default_factory=list)
    new_production_files: list[str] = Field(default_factory=list)
    existing_test_files_modified: list[str] = Field(default_factory=list)
    new_test_files: list[str] = Field(default_factory=list)
    other_files_changed: list[str] = Field(default_factory=list)
    production_lines_added: int = Field(ge=0)
    production_lines_deleted: int = Field(ge=0)
    test_lines_added: int = Field(ge=0)
    test_lines_deleted: int = Field(ge=0)
    protocol_core_files_modified: list[str] = Field(default_factory=list)


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
