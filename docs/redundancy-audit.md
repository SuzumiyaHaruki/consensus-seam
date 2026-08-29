# Python 代码冗余审计

审计日期：2026-08-29

## 结论

本轮没有发现无引用的生产模块、完全重复的生产函数或第二套能力模型。已删除
未被工作流调用的 `route_review`，并合并了一处分支重复校验。PDF 及其生成脚本
已移到仓库外的 `/home/nitro/Desktop/ConsensusSeam展示材料/`。

Agent 2 在不同能力实现单元中收到完整分析报告、能力规范和修改策略属于有意
保留：这些内容为模型提供源码修改所需的完整上下文，不能因文本看起来重复就
截断。结构化输出校验失败后的第二次尝试也继续携带完整原任务和上次输出。

## 已清理或收紧的内容

- 作废候选统一删除顶层补丁、接口、Reviewer、统计和验证报告，只在日志中
  保留作废原因；终态不再重新制造空补丁。
- `runs/latest/<project>/` 排除所有生成 worktree；只有结果明确为 `PASS` 或
  `REPAIRED` 且存在补丁时，`APPLY.md` 才给出应用命令。
- 生成后 `repair` 只接受 Reviewer 已通过且工作流结果可用的候选；消息捕获
  与注入共享 Controller 时继续作为一个实现单元修订。
- 删除旧的单条 `suggested_direction` 输出字段；读取旧报告时只做一次迁移，
  不向新 Agent schema 暴露旧字段。
- Agent 工具不再反复运行无过滤的 Go 包测试。此前 HashiCorp 目标上出现过
  四次 120 秒全测试超时，因此工具层只允许精确 `TestName`；完整回归仍由
  Controller/Verifier 执行。

## 刻意保留的相似结构

- `BaselineVerifier` 与候选 Verifier 的失败含义和输出不同，保留两个短入口。
- 首次生成允许回到 Analyzer；`repair` 明确禁止重新分析。两套状态机只共享
  无状态步骤，不用模式布尔值强行合并。
- `materialized_verification_fixtures` 是旧调用方兼容入口，实际实现委托给
  `materialized_fixtures`。
- Analyzer、Transformer、Reviewer 的短构造函数形状相同，但分别绑定不同
  输出模型、Prompt 和工具权限，不值得增加抽象层。

## 剩余维护风险

`consensus_seam/workflow.py` 仍是最大文件，体积来自显式的生成、重分析、复审
和可选 repair 状态转移。当前未发现可安全删除的重复状态分支；继续增加新的
工作流种类时，应再考虑按首次生成与生成后修复拆分模块。测试代码主要覆盖
终止、候选继承、审计导出和工具边界，没有增加目标协议专用测试矩阵。

## 验证与规模

- `pytest`：80 项通过；
- `python -m compileall -q consensus_seam tests`：通过；
- `python -m consensus_seam --help`：通过；
- `git diff --check`：通过；
- 生产 Python：5556 个物理行，其中 `workflow.py` 1275 行；
- Controller 测试 Python：3159 个物理行。
