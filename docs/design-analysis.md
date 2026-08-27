# ConsensusSeam v0.1 design analysis

## Core interpretation

ConsensusSeam is a testability transformer, not a test-strategy system. The
controller owns bounded orchestration and validated artifacts. The three Agents
own separate semantic roles, and the deterministic verifier owns execution. A
Pending Store may retain and expose concrete messages, but it must not choose a
delivery order or time.

The most important design property is the boundary attached to every capability
claim. A protocol-core output API does not automatically cover serialization,
application transport, retry behavior, or a real network send. Likewise, an
existing constructor does not prove lifecycle control unless the implementation
already defines state ownership across restart.

## Strong parts of the specification

- The `SUPPORTED / PATCHABLE / PARTIAL / INVASIVE / UNKNOWN /
  NOT_APPLICABLE` vocabulary prevents binary, overconfident classifications.
- Agent 2 acts only on `PATCHABLE`; rediscovered invasiveness stops that change.
- Agent 3 is independent and read-only; executable verification remains ordinary
  code rather than another Agent opinion.
- Go-only target support and provider-neutral LLM integration keep v0.1 narrow.
- Message identity is control-plane identity rather than protocol identity. It
  does not depend on term, height, payload, or a content hash.
- The non-goals correctly exclude scheduling policy, full virtual time, invented
  restart semantics, and premature cross-language abstractions.

## Framework decisions implemented here

- Python 3.10+ is used to match the local machine; no 3.12-only feature is needed.
- Pydantic rejects invalid or extra Agent fields before another Agent receives
  them. Evidence-bearing findings and review consistency are validated.
- The Controller is an explicit bounded state machine. Agents do not converse
  freely and cannot decide routing.
- Every transformation attempt uses a fresh detached Git worktree. The target
  source tree is not edited.
- Configured commands execute without an implicit shell.
- Agent prompts and specs are included in built wheels as runtime resources.
- A bounded DeepSeek Chat Completions runtime executes role-scoped local tools and
  preserves thinking-mode reasoning content between tool turns.
- A deterministic `FakeLLMClient` keeps orchestration testable without credentials.
- Go receiver methods such as `RawNode.Ready` are resolved through a small
  `go/parser`/`go/ast` helper rather than only a regular expression.
- Target manifests define `system_boundary`, per-Agent models, and named
  capability checks. Full runs reject unverified implementation claims.
- Existing tracked Go tests are protected through Git's committed baseline; new
  capability tests remain allowed. No additional content hashes are introduced.
- `INVASIVE_REDISCOVERED` always invalidates the entire current worktree.
- Tool output is uniformly bounded, and live Agent runs record aggregate usage
  and timing without storing model reasoning content.

## Deliberately incomplete after the framework milestone

This repository does not yet claim the message-control vertical slice. The next
implementation phase must add a Mini Raft target and demonstrate all of the
following with generated Go tests:

1. capture increases `ListPending()`;
2. capture suppresses the original send;
3. `Inject(M2)` consumes only M2 and preserves M1;
4. the same seed produces the same protocol-relevant random choices;
5. ambiguous lifecycle recovery is classified `INVASIVE` and not modified.

A live authenticated DeepSeek run is still required to validate model behavior,
tool-choice quality, token usage, and retry behavior against the real service.

`SUPPORTED` findings in analyze-only/no-patch runs are not dynamically verified
yet. A future opt-in supported-capability verification mode may execute manifest
checks, particularly for the etcd-raft classification experiment.

Capability-test routing is now wired through the manifest and workflow. The Mini
Raft target must provide separate MC1/MC2/MC3 commands; without them, a full run
returns `SEMANTIC_AMBIGUITY` after build and regression tests.

## Main engineering risks for the next phase

- Missing outbound bypasses are the highest semantic risk. Snapshot, retry,
  heartbeat, and forwarded-request paths must be inspected separately.
- Captured Go messages may contain mutable slices, maps, pointers, or protobuf
  internals. The patch must demonstrate a safe copy strategy.
- Async implementations cannot imply quiescence from `Inject` returning. v0.1
  should preserve that limitation rather than invent `WaitForQuiescence`.
- A worktree begins at a Git commit. Target selection should therefore identify
  the intended committed revision; the framework does not silently copy unrelated
  dirty working-tree state into a transformation attempt.
