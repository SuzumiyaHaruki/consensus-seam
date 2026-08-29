# Python 代码冗余审计

审计日期：2026-08-29

## 结论

核心工作流现只保留 `analyze`、`patch` 和 `run`。生成后由人工编写测试再触发
Agent 2 的 `repair` 流程已移除；实现问题统一由 `patch` 中的 Agent 3 自动反馈
闭环处理。没有发现无引用的生产模块或第二套能力模型。

Agent 2 在不同能力实现单元中收到完整分析报告、能力规范和修改策略属于有意
保留：这些内容为模型提供源码修改所需的完整上下文，不能因文本看起来重复就
截断。结构化输出校验失败后的第二次尝试也继续携带完整原任务和上次输出。

## 已清理或收紧的内容

- 删除 `repair` CLI、后置检查清单模型、候选恢复校验、专用 worktree 循环、
  状态枚举、示例材料及对应单元/集成测试。
- 删除只为旧调用方保留的 `materialized_verification_fixtures` 包装入口，调用方
  直接使用统一的 `materialized_fixtures`。
- Agent 2 测试要求压缩为短约束：只测本实现单元新增行为、复用 fixture、每个
  单元最多一个端到端场景、Reviewer 每个问题只加一个最小回归，测试代码通常
  小于对应生产修改。
- 新增文件夹级源码边界：`scope_roots` 可读写，`evidence_roots` 只读；路径、
  符号查询和补丁写入共用同一机械权限检查。
- 作废候选、`runs/latest/<project>/`、精确 Go 测试名和完整回归边界等已有安全
  处理继续保留。

## 刻意保留的相似结构

- `BaselineVerifier` 与候选 Verifier 的失败含义和输出不同，保留两个短入口。
- Analyzer、Transformer、Reviewer 的短构造函数形状相同，但分别绑定不同
  输出模型、Prompt 和工具权限，不值得增加抽象层。
- `patch` 与 `run` 共用同一生成状态机，`verify` 只控制是否执行已配置的
  baseline、原测试和能力检查，没有复制第二套实现。

## 剩余维护风险

`consensus_seam/workflow.py` 的主要体积来自生成、重分析和复审的显式状态转移；
`models.py` 的体积来自七项能力及跨字段约束。当前继续抽象这两部分只会移动
代码而不会实质瘦身。测试代码主要覆盖终止、候选继承、审计导出和工具边界。

## 验证与规模

- `pytest`：77 项通过；
- `python -m compileall -q consensus_seam tests`：通过；
- `python -m consensus_seam --help`：通过；
- `git diff --check`：通过；
- 生产 Python：5218 个物理行，其中 `workflow.py` 873 行；
- Controller 测试 Python：2910 个物理行。
