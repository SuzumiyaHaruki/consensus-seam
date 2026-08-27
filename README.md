# ConsensusSeam v0.1

ConsensusSeam is a Python controller for analyzing the test-control seams of Go
consensus implementations. It separates three roles:

1. a read-only capability analyzer;
2. a low-intrusion transformer that may act only on `PATCHABLE` findings;
3. an independent, read-only reviewer.

A deterministic verifier, not an Agent, runs the configured build and test
commands. The current repository is the first runnable framework: it provides
validated configuration and Agent I/O, prompts, a DeepSeek Chat Completions tool
runtime, a fake runtime, an explicit workflow, a thin Go backend, isolated Git
worktrees, artifact reporting, and tests. It does not yet claim the Mini Raft
message-control vertical slice or a live authenticated DeepSeek run.

## Requirements

- Python 3.10+
- Git
- Go for Go targets

## Install and test

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest
```

## CLI

For a real run, keep the API key outside the repository:

```bash
export DEEPSEEK_API_KEY='...'
consensus-seam analyze --project targets/my-target/project.yaml
```

Or place the raw key on one line in a file outside version control:

```bash
mkdir -p .secrets
chmod 700 .secrets
${EDITOR:-vi} .secrets/deepseek-api-key.txt
chmod 600 .secrets/deepseek-api-key.txt
consensus-seam analyze \
  --project targets/my-target/project.yaml \
  --api-key-file .secrets/deepseek-api-key.txt
```

`DEEPSEEK_API_KEY_FILE` can provide the same path without a CLI flag. Key file
contents are never written to run artifacts or logs.

`DEEPSEEK_BASE_URL` may override `https://api.deepseek.com` for a compatible
gateway. `--model-profile manifest|mixed|all-flash|all-pro` supports controlled
model comparisons. The default `manifest` profile reads per-Agent settings from
`project.yaml`.

```bash
consensus-seam analyze --project targets/my-target/project.yaml \
  --responses responses.json

consensus-seam patch --project targets/my-target/project.yaml \
  --responses responses.json

consensus-seam run --project targets/my-target/project.yaml \
  --responses responses.json
```

`--responses` is a deterministic development adapter. Its JSON file contains an
array of raw Agent responses, consumed in order. A real tool-capable Agent/LLM
runtime is selected automatically when `DEEPSEEK_API_KEY` is present.

The Analyzer can list, read, and search source plus query Go declarations; it
cannot edit source or run target tests. The Transformer gets the same inspection
tools plus bounded `apply_patch` and `write_file` operations scoped to its Git
worktree. The Reviewer gets separate read-only `original` and `patched` scopes.
All tool responses are capped before returning to the model.

Existing tracked Go tests are mechanically protected: Agent 2 may create new
`*_test.go` files but a worktree that modifies an existing one is discarded.
Likewise, any `INVASIVE_REDISCOVERED` result discards that entire worktree before
the remaining capabilities are retried from `HEAD`.

Every target manifest must state its `system_boundary`. A full `run` also expects
deterministic `capability_checks` for every implemented capability. Missing MC1,
MC2, MC3, or equivalent checks produces `SEMANTIC_AMBIGUITY`, rather than a false
success based only on the original test suite.

An optional `transform_capabilities` allowlist scopes one experiment without
weakening analysis. Agent 1 still classifies all seven capabilities, while Agent 2
may modify only findings that are both `PATCHABLE` and selected. PATCHABLE
findings outside the scope remain visible in `capability-report.json` and are
recorded in `unresolved.json` as intentionally skipped.

Each invocation writes structured artifacts below `runs/<run-id>/`. The original
target repository is never modified by the transformer path; modifications are
made in a detached Git worktree. Live runtimes also write `agent-run-stats.json`
with model, API/tool-call counts, token usage, cache tokens, and timing. It never
stores `reasoning_content`. Temporary 429, 5xx, and network failures are retried
up to three times with bounded exponential backoff.

On completion, audit-sized artifacts are also published to the Git-tracked
`runs/latest/` directory. It contains reports, `changes.patch`, statistics, and
logs, but excludes patched worktrees. Publishing updates local Git content only;
the workflow never commits or pushes to a remote repository automatically.

See `CODEX_SPEC.md` for the non-goals and `spec/` for the capability and change
policies. The current implementation boundary and next vertical slice are
documented in `docs/design-analysis.md`. Inputs needed for live runs are listed in
`docs/required-materials.md`.
