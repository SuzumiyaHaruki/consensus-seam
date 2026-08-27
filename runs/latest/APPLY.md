# 应用最近一次已验证补丁

修改目标仓库前，先审查 `changes.patch`、`review-report.json` 和 `verification-report.json`，并在 `run-config.json` 中确认目标提交版本。

然后在目标仓库中运行：

```bash
git apply --check /绝对路径/runs/latest/changes.patch
git apply /绝对路径/runs/latest/changes.patch
go test ./...
```

ConsensusSeam 不会自动应用或提交补丁。

如果最近一次运行是 analyze-only，目录中可能没有 `changes.patch`；此时本文件只说明通用应用流程。
