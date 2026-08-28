# 实验产物目录

ConsensusSeam 每次调用会创建一个独立的 `runs/<run-id>/` 目录。带时间戳的完整运行目录默认由 Git 忽略。

运行结束后，报告、补丁、统计和日志会复制到
`runs/latest/<project>/`，只覆盖同一目标的上一次审计导出。Git 会同时跟踪
各目标的最近一次导出；体积较大的 detached patched worktree 永远不会复制
进 `latest`。

每个项目目录分别反映该目标最近一次运行类型。一次 analyze-only 实验会替换
同一目标上一轮完整 run 的导出文件，但不会影响其他目标。

框架不会自动提交、推送或把补丁应用到目标仓库。
