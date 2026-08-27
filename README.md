# ConsensusSeam v0.1

ConsensusSeam is a Python controller for analyzing the test-control seams of Go
consensus implementations. It separates three roles:

1. a read-only capability analyzer;
2. a low-intrusion transformer that may act only on `PATCHABLE` findings;
3. an independent, read-only reviewer.

A deterministic verifier, not an Agent, runs the configured build and test
commands. The current repository is the first runnable framework: it provides
validated configuration and Agent I/O, prompts, a fake LLM client, an explicit
workflow, a thin Go backend, isolated Git worktrees, artifact reporting, and
unit tests. It does not yet claim the Mini Raft message-control vertical slice.

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
adapter can implement the same `LLMClient` protocol later without changing the
workflow. No model vendor is selected by v0.1.

Each invocation writes structured artifacts below `runs/<run-id>/`. The original
target repository is never modified by the transformer path; modifications are
made in a detached Git worktree.

See `CODEX_SPEC.md` for the non-goals and `spec/` for the capability and change
policies. The current implementation boundary and next vertical slice are
documented in `docs/design-analysis.md`.
