"""Controller 与所有 Agent 共用的强校验数据合同。"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 可用能力的集合。该集合是 v0.1 的研究任务定义，不是从具体 Raft 项目
# 推导出来的；所有 Analyzer 输出都必须完整覆盖这些能力。
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
    """所有外部数据模型的严格基类。

    extra="forbid" 防止模型悄悄创造 Schema 外字段；validate_assignment
    保证工作流后续修改对象（例如 INVASIVE_REDISCOVERED）时仍执行校验。
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CommandConfig(StrictModel):
    command: str = Field(min_length=1)


class FailureCode(str, Enum):
    """Verifier 可产生的机器可路由失败类型。"""

    BASELINE_FAILED = "BASELINE_FAILED"
    BUILD_FAILED = "BUILD_FAILED"
    MESSAGE_CAPTURE_FAILED = "MESSAGE_CAPTURE_FAILED"
    MESSAGE_SUPPRESSION_FAILED = "MESSAGE_SUPPRESSION_FAILED"
    MESSAGE_INJECTION_FAILED = "MESSAGE_INJECTION_FAILED"
    MESSAGE_INJECTION_RETENTION_FAILED = "MESSAGE_INJECTION_RETENTION_FAILED"
    TIME_CONTROL_FAILED = "TIME_CONTROL_FAILED"
    RANDOMNESS_CONTROL_FAILED = "RANDOMNESS_CONTROL_FAILED"
    LIFECYCLE_CONTROL_FAILED = "LIFECYCLE_CONTROL_FAILED"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"
    REGRESSION_FAILED = "REGRESSION_FAILED"
    SEMANTIC_AMBIGUITY = "SEMANTIC_AMBIGUITY"


# capability → 一次完整 run 至少需要的基础检查类型。这里不再把某个目标的
# 额外严格检查提升成所有目标的强制要求。
CAPABILITY_CHECK_CODES: dict[str, frozenset[FailureCode]] = {
    "message_capture": frozenset({FailureCode.MESSAGE_CAPTURE_FAILED}),
    "message_injection": frozenset({FailureCode.MESSAGE_INJECTION_FAILED}),
    "time_control": frozenset({FailureCode.TIME_CONTROL_FAILED}),
    "randomness_control": frozenset({FailureCode.RANDOMNESS_CONTROL_FAILED}),
    "lifecycle_control": frozenset({FailureCode.LIFECYCLE_CONTROL_FAILED}),
    "observation": frozenset({FailureCode.OBSERVATION_FAILED}),
}

# 目标 evaluation 仍可配置比基础要求更严格的检查。Mini Raft 的自动发送
# 抑制和失败投递保留就是目标专属附加检查，但不再阻止其他结构不同的目标运行。
CAPABILITY_ALLOWED_CHECK_CODES: dict[str, frozenset[FailureCode]] = {
    **CAPABILITY_CHECK_CODES,
    "message_capture": CAPABILITY_CHECK_CODES["message_capture"]
    | {FailureCode.MESSAGE_SUPPRESSION_FAILED},
    "message_injection": CAPABILITY_CHECK_CODES["message_injection"]
    | {FailureCode.MESSAGE_INJECTION_RETENTION_FAILED},
}

CAPABILITY_FAILURE_CODES = frozenset(
    code for codes in CAPABILITY_ALLOWED_CHECK_CODES.values() for code in codes
)


class SystemBoundary(StrictModel):
    kind: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ExperimentConfig(StrictModel):
    """实验性质及其可公开研究主张。"""

    kind: Literal["engineering_smoke", "blind_capability", "repair"]
    oracle_visible_to_agents: bool
    research_claim: str = Field(min_length=1)


class AgentModelConfig(StrictModel):
    """单个 Agent 的模型与推理预算。"""

    model: str = Field(min_length=1)
    thinking: Literal["enabled", "disabled"] = "enabled"
    reasoning_effort: Literal["low", "high", "max"] = "high"
    max_tokens: int = Field(default=32768, ge=1024, le=384000)


class LLMConfig(StrictModel):
    """三个 Agent 的独立模型配置；Reviewer 默认使用更强模型。"""

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
    """一个由 Controller 执行、Agent 不可见的能力检查。"""

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


def _validate_capability_check_configs(
    checks: list[CapabilityCheckConfig],
) -> None:
    """复用 capability check 名称和 failure-code 一致性校验。"""

    names = [check.name for check in checks]
    if len(names) != len(set(names)):
        raise ValueError("capability check names must be unique")
    for check in checks:
        if check.failure_code not in CAPABILITY_ALLOWED_CHECK_CODES[check.capability]:
            raise ValueError(
                f"{check.failure_code.value} is not valid for {check.capability}"
            )


class VerificationFixtureConfig(StrictModel):
    """隐藏文件从评测目录到临时 worktree 的复制规则。"""

    source: Path
    destination: Path

    @model_validator(mode="after")
    def destination_must_be_relative(self) -> "VerificationFixtureConfig":
        # destination 最终会参与文件写入，因此必须是安全相对路径；.git
        # 即使仍在 worktree 内也属于禁止触碰的版本控制元数据。
        if self.destination.is_absolute() or ".." in self.destination.parts:
            raise ValueError("verification fixture destination must stay in the worktree")
        if ".git" in self.destination.parts:
            raise ValueError("verification fixture cannot target .git")
        return self


class PostHocCheckManifest(StrictModel):
    """生成后测试使用的独立检查清单。"""

    capability_checks: list[CapabilityCheckConfig] = Field(min_length=1)
    verification_fixtures: list[VerificationFixtureConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_checks(self) -> "PostHocCheckManifest":
        _validate_capability_check_configs(self.capability_checks)
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
    """固定状态机的有界重试预算，防止 Agent 无限自循环。"""

    agent1_reanalysis_rounds: int = Field(default=2, ge=1, le=10)
    agent2_patch_rounds: int = Field(default=3, ge=1, le=10)


class ProjectManifest(StrictModel):
    """项目 YAML 的完整强类型表示。"""

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
        """检查实验选择和失败码之间的静态一致性。"""

        if self.transform_capabilities is not None:
            if not self.transform_capabilities:
                raise ValueError("transform_capabilities cannot be empty")
            if len(self.transform_capabilities) != len(set(self.transform_capabilities)):
                raise ValueError("transform_capabilities must be unique")
        _validate_capability_check_configs(self.capability_checks)
        return self


class CapabilityDefinition(StrictModel):
    """能力的通用描述、允许形式、义务和公开测试契约。"""

    description: str = Field(min_length=1)
    accepted_v0_forms: list[str] = Field(default_factory=list)
    obligations: dict[str, str] = Field(default_factory=dict)
    testing_contract: dict[str, str] = Field(default_factory=dict)


class CapabilityPrerequisites(StrictModel):
    target_language: dict[str, list[str]] = Field(default_factory=dict)


class CapabilitySpec(StrictModel):
    """内置能力规范；所有目标项目共享，不包含目标 oracle。"""

    version: int = Field(ge=1)
    capabilities: dict[str, CapabilityDefinition]
    prerequisites: CapabilityPrerequisites = Field(
        default_factory=CapabilityPrerequisites
    )

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
    """可由审计者定位回源码的证据。"""

    file: str | None = None
    symbol: str | None = None
    line: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_location(self) -> "CodeEvidence":
        # reason 只是解释，不能替代定位信息；否则 Reviewer 可以用泛泛描述
        # 伪装成代码证据。
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
    """某项能力义务的状态、证据和判定理由。"""

    status: ObligationStatus
    evidence: list[CodeEvidence] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def satisfied_requires_evidence(self) -> "ObligationAssessment":
        if self.status is ObligationStatus.SATISFIED and not self.evidence:
            raise ValueError("SATISFIED obligation requires code evidence")
        return self


class CapabilityFinding(StrictModel):
    """Agent 1 对单项能力的完整结论。"""

    status: CapabilityStatus
    evidence: list[CodeEvidence] = Field(
        default_factory=list,
        description=(
            "Top-level capability evidence. SUPPORTED, PATCHABLE, and PARTIAL "
            "require at least one item even when execution_paths or obligation "
            "evidence are present."
        ),
    )
    boundary: str | None = None
    gap: str | None = None
    reason: str | None = None
    limitations: list[str] = Field(default_factory=list)
    suggested_direction: str | None = None
    entrypoints: list[str] = Field(default_factory=list)
    usage_examples: list[str] = Field(
        default_factory=list,
        description=(
            "Short target-language examples for directly usable existing interfaces. "
            "They document usage and do not define test policy."
        ),
    )
    existing_test_interface_complete: bool = Field(
        default=False,
        description=(
            "Whether existing target APIs already satisfy the complete test "
            "capability without adding target code."
        ),
    )
    test_support_reason: str | None = Field(
        default=None,
        description=(
            "Explanation of why existing primitives are or are not a complete "
            "test-facing interface."
        ),
    )
    suggested_changes: list[str] = Field(
        default_factory=list,
        description=(
            "Evidence-backed low-intrusion options such as wrappers, hooks, "
            "dependency injection, configuration, accessors, or harness changes."
        ),
    )
    # 只记录输入/输出边界或运行模型实质不同的公开路径，不展开协议内部每个分支。
    execution_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Materially distinct public execution paths discovered inside the "
            "system boundary; this does not replace top-level code evidence."
        ),
    )
    obligations: dict[str, "ObligationAssessment"] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_supporting_explanation(self) -> "CapabilityFinding":
        # 正向声称必须有代码证据；UNKNOWN/INVASIVE 至少要说明为什么无法
        # 安全支持，防止只输出标签而没有可审计依据。
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
        if self.status is not CapabilityStatus.NOT_APPLICABLE and not self.test_support_reason:
            raise ValueError(f"{self.status.value} requires test_support_reason")
        if self.status is CapabilityStatus.SUPPORTED:
            if not self.existing_test_interface_complete:
                raise ValueError("SUPPORTED requires a complete existing test interface")
            if self.gap:
                raise ValueError("SUPPORTED capability cannot declare a gap")
        if self.status is CapabilityStatus.PATCHABLE:
            if self.existing_test_interface_complete:
                raise ValueError("PATCHABLE cannot have a complete existing test interface")
            if not self.suggested_changes:
                raise ValueError("PATCHABLE requires suggested_changes")
        return self


class CapabilityReport(StrictModel):
    """Agent 1 的顶层报告及跨字段一致性约束。"""

    target: str = Field(min_length=1)
    capabilities: dict[str, CapabilityFinding]

    required_capabilities: ClassVar[frozenset[str]] = CAPABILITY_NAMES

    @model_validator(mode="after")
    def require_exact_v0_capabilities(self) -> "CapabilityReport":
        # Agent 不能遗漏“不好判断”的能力，也不能临时创造第八种能力。
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
        if (
            self.capabilities["message_injection"].status
            is CapabilityStatus.SUPPORTED
            and self.capabilities["message_capture"].status
            is not CapabilityStatus.SUPPORTED
        ):
            raise ValueError(
                "SUPPORTED message_injection requires SUPPORTED message_capture"
            )
        self._validate_lifecycle_obligations()
        self._validate_external_input_obligations()
        return self

    def _validate_lifecycle_obligations(self) -> None:
        """保持 v0.1 可用性控制简单，同时记录但不发明 crash 语义。"""

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
            states[name] is not ObligationStatus.SATISFIED
            for name in {"stop_boundary", "restart_or_recovery_boundary"}
        ):
            raise ValueError(
                "SUPPORTED lifecycle_control requires unavailable and restore boundaries"
            )

    def _validate_external_input_obligations(self) -> None:
        """强制区分应用工作负载、协议 ingress 与内部定时事件。"""

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
        """返回 PATCHABLE 能力，并可与本次实验 allowlist 求交集。"""

        result = {
            name
            for name, finding in self.capabilities.items()
            if finding.status is CapabilityStatus.PATCHABLE
        }
        return result if allowlist is None else result & set(allowlist)

    def apply_rediscovered(self, names: set[str]) -> None:
        """把 Transformer 实作时发现的侵入性反馈合并回分析报告。"""

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
    """Agent 2 对一项已实现接口的结构化说明。"""

    implemented: bool
    rediscovered_status: Literal["INVASIVE_REDISCOVERED"] | None = None
    capture_boundary: CodeLocation | None = None
    pending_store: CodeLocation | None = None
    entrypoint: CodeLocation | None = None
    public_entrypoints: list[CodeLocation] = Field(
        default_factory=list,
        description=(
            "Every generated or wrapped callable entrypoint intended for the "
            "declared test consumer. Internal hooks belong in other location fields."
        ),
    )
    copy_strategy: str | None = None
    production_mode: str | None = None
    test_mode: str | None = None
    instance_reference: str | None = Field(
        default=None,
        description=(
            "How enumeration identifies one concrete cache instance and how long "
            "that reference remains stable."
        ),
    )
    target_binding_strategy: str | None = Field(
        default=None,
        description=(
            "How a cached destination is resolved or validated against the real "
            "target object before normal protocol ingress."
        ),
    )
    cache_effects: str | None = Field(
        default=None,
        description=(
            "Cache effects of enumerate, take, drop, success, synchronous failure, "
            "and unconfirmed asynchronous delivery."
        ),
    )
    message_id_scope: Literal[
        "pending_store_instance", "test_session", "node", "global"
    ] | None = None
    # 兼容已有实验报告；具体目标可以声明串行控制器，但 v0.1 不再要求
    # 所有目标都采用同一种并发模型。
    controller_operations: Literal["serialized"] | None = None
    # Agent 2 必须说明它实际覆盖了哪些 Analyzer 发现的路径，以及哪些路径
    # 因低侵入边界而保留。二者只是审计信息，不引入逐路径工作流状态机。
    covered_paths: list[str] = Field(default_factory=list)
    uncovered_paths: list[str] = Field(default_factory=list)
    implementation_approach: list[str] = Field(
        default_factory=list,
        description=(
            "Actual low-intrusion techniques used by Agent 2, such as wrapper, "
            "hook, dependency injection, configuration, accessor, or harness extension."
        ),
    )
    usage_examples: list[str] = Field(
        default_factory=list,
        description=(
            "Short target-language examples showing setup and interface calls. "
            "Test scheduling and message-selection policy stay with the user."
        ),
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> "InterfaceCapability":
        if self.implemented and self.rediscovered_status is not None:
            raise ValueError("an implemented capability cannot be rediscovered as invasive")
        if not self.implemented and self.rediscovered_status is None:
            raise ValueError("an unimplemented PATCHABLE capability needs rediscovered_status")
        return self


class InterfaceReport(StrictModel):
    """Agent 2 输出；仅覆盖本轮被选择的 PATCHABLE 能力。"""

    message_capture: InterfaceCapability | None = None
    message_injection: InterfaceCapability | None = None
    time_control: InterfaceCapability | None = None
    randomness_control: InterfaceCapability | None = None
    lifecycle_control: InterfaceCapability | None = None
    observation: InterfaceCapability | None = None

    @model_validator(mode="after")
    def require_one_capability(self) -> "InterfaceReport":
        # 控制引用可以是 ID、handle、下标、缓存记录或目标原生形式；模型保留
        # message_id_scope 以兼容已有结果，但不再把数字 ID 作为功能合同。
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


class ReviewCheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReviewCheck(StrictModel):
    """Reviewer 对一个命名审计问题的结论。"""

    name: str = Field(min_length=1)
    result: ReviewCheckResult
    evidence: list[CodeEvidence] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @field_validator("evidence", mode="before")
    @classmethod
    def discard_unlocated_supplementary_evidence(cls, value: object) -> object:
        # 模型偶尔会把“其余文件未修改”一类全局结论放进 evidence，并把
        # file/symbol 设为 null。这类项目属于 reason，不应让整个报告失败；
        # 这里仅删除无定位的附加项，后面的校验仍要求 PASS 至少有一条证据。
        if not isinstance(value, list):
            return value
        return [
            item
            for item in value
            if not isinstance(item, dict) or item.get("file") or item.get("symbol")
        ]

    @model_validator(mode="after")
    def pass_requires_evidence(self) -> "ReviewCheck":
        if self.result is ReviewCheckResult.PASS and not self.evidence:
            raise ValueError("PASS review check requires evidence")
        return self


class ReviewReport(StrictModel):
    """Agent 3 的结构化语义审计报告。"""

    overall: ReviewOverall
    checks: list[ReviewCheck]
    issues: list[ReviewIssue] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    required_checks: ClassVar[frozenset[str]] = frozenset(
        {
            "original_send_suppressed",
            "protocol_logic_unchanged",
            "exact_target_preserved",
            "message_cache_injection_coherence",
            "existing_tests_unchanged",
            "testing_contract_conformance",
        }
    )

    @model_validator(mode="after")
    def require_consistent_issues(self) -> "ReviewReport":
        # 所有必需检查都必须出现。PASS 不能同时携带 issue，也不能隐藏
        # FAIL/UNKNOWN；非 PASS 则必须明确指出至少一个问题。
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

    def validate_for_interface(self, interface_report: InterfaceReport) -> None:
        """根据 Agent 2 实际实现的能力，收紧 PASS 所需检查。"""

        if self.overall is not ReviewOverall.PASS:
            return
        required = {
            "protocol_logic_unchanged",
            "existing_tests_unchanged",
            "testing_contract_conformance",
        }
        capture = interface_report.message_capture
        if capture is not None and capture.implemented:
            required.add("original_send_suppressed")
        injection = interface_report.message_injection
        if injection is not None and injection.implemented:
            required.add("exact_target_preserved")
        if (capture is not None and capture.implemented) or (
            injection is not None and injection.implemented
        ):
            required.add("message_cache_injection_coherence")
        results = {check.name: check.result for check in self.checks}
        invalid = {
            name
            for name in required
            if results.get(name) is not ReviewCheckResult.PASS
        }
        if invalid:
            raise ValueError(
                "PASS review requires applicable checks PASS: "
                + ", ".join(sorted(invalid))
            )


class FailureRoute(str, Enum):
    AGENT1 = "AGENT1"
    AGENT2 = "AGENT2"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    NONE = "NONE"


class CommandExecution(StrictModel):
    """一次外部命令的可审计结果；stdout/stderr 均按原样记录。"""

    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = Field(ge=0)

    @property
    def passed(self) -> bool:
        return self.returncode == 0


class PatchMetrics(StrictModel):
    """基于 Git diff 计算的低侵入性指标。"""

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
    REPAIRED = "REPAIRED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class WorkflowResult(StrictModel):
    """CLI 最终输出；run_directory 指向本次完整或失败运行目录。"""

    outcome: WorkflowOutcome
    run_directory: Path
    reason: str | None = None
