# etcd/raft analyze-only evaluation

This directory defines an exploratory Agent 1 analysis of the standalone
`go.etcd.io/raft/v3` repository. It deliberately contains no human ground truth,
hidden acceptance test, transformation allowlist, or capability check.

## Pinned target

```text
repository: https://github.com/etcd-io/raft.git
branch:     release-3.6
commit:     91180476b404beeb5326194e3fcdfa1758d4f222
module:     go.etcd.io/raft/v3
```

The target clone is expected at:

```text
/home/nitro/Desktop/etcd-raft
```

Both the target and ConsensusSeam repositories must be clean before the formal
analyze command starts. The target repository must not contain ConsensusSeam
prompts, expected classifications, or custom answer hints.

## Toolchain note

The pinned branch currently declares:

```text
go 1.26
toolchain go1.26.7
```

The local machine currently has Go 1.25.8. `consensus-seam analyze` does not run
the configured build or test commands, so source analysis can proceed without
downloading Go 1.26.7. A later baseline, patch, or full run must first use a
compatible Go toolchain and pass `go test ./...` on the untouched target.

## Scope

Inside the boundary:

- the standalone raft module and its public protocol state-machine APIs;
- Ready processing and message/state outputs;
- Storage contracts and module-provided storage implementations;
- membership-change and asynchronous-storage-write behavior.

Outside the boundary:

- real network transport and RPC code;
- external disk, WAL, and database implementations;
- application state-machine logic;
- process lifecycle and supervision provided by an integrating system;
- the full etcd server repository.

## Run

Use only the `analyze` command for this first experiment:

```bash
cd /home/nitro/Desktop/consensus-seam
. .venv/bin/activate

consensus-seam analyze \
  --project /home/nitro/Desktop/consensus-seam/evaluation/etcd-raft/project.yaml \
  --api-key-file /home/nitro/Desktop/ds.txt \
  --model-profile manifest
```

Expected artifacts are the Agent 1 capability report, unresolved findings,
runtime statistics, tool audit, and run configuration. Results are reviewed
qualitatively; this exploratory run does not claim classification accuracy.
