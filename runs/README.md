# Run artifacts

ConsensusSeam creates one subdirectory per invocation. Generated run directories
are ignored by Git. After a run finishes, reports, the exported patch, statistics,
and logs are copied to `runs/latest/`, replacing the previous audit export. Git
tracks only that latest export; detached patched worktrees are always excluded.
