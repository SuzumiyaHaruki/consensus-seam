# 实验产物目录

ConsensusSeam 每次调用会创建一个独立的 `runs/<run-id>/` 目录。带时间戳的完整运行目录默认由 Git 忽略。

运行结束后，报告、补丁、统计和日志会复制到 `runs/latest/`，覆盖上一次审计导出。Git 只跟踪最近一次导出；体积较大的 detached patched worktree 永远不会复制进 `latest`。

`runs/latest` 反映最近一次运行类型。一次 analyze-only 实验会替换上一轮完整 run 的导出文件，因此提交前应先确认这确实是希望公开审计的实验。

框架不会自动提交、推送或把补丁应用到目标仓库。
