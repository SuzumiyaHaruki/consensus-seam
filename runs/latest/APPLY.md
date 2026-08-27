# Applying the latest verified patch

Review `changes.patch`, `review-report.json`, and `verification-report.json`
before modifying the target repository. Confirm the expected target revision in
`run-config.json`, then run from the target repository:

```bash
git apply --check /absolute/path/to/runs/latest/changes.patch
git apply /absolute/path/to/runs/latest/changes.patch
go test ./...
```

ConsensusSeam deliberately does not apply or commit the patch automatically.
