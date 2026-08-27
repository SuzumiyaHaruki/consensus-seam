# 评测专用材料

本目录保存具体目标的正式评测输入。它们不进入 Agent Prompt，也不在目标仓库的源码工具范围内。

每个目标可以拥有自己的：

- `project.yaml`；
- 基础或隐藏能力检查；
- fixture 映射；
- 人工 ground truth；
- 目标专属限制说明。

目标专属检查只用于该目标，不能因为一次实验失败就提升为全局能力合同。

Mini Raft 的 `hidden-acceptance/` 只在 Agent 3 返回后临时复制到候选 worktree，验证结束后删除。所有 Agent 获得的都是已经去除检查命令、fixture 路径和 ground truth 的项目视图。
