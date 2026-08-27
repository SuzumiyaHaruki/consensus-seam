# Python 代码冗余审计

审计日期：2026-08-27

## 结论

本轮没有发现无引用模块、重复模型或可以直接删除而不改变行为的生产代码。新增的生成后修复流程没有复制 Analyzer，也不会重新执行能力分析；运行时只调用 Transformer 和 Reviewer。

审计中已经清理以下重复实现：

- 项目清单与生成后检查清单共用 capability check 校验；
- 两类清单共用 evaluator-only fixture 的路径解析和安全检查；
- `patch`、`run` 与 `repair` 共用候选格式化、构建、补丁统计和 Reviewer 调用；
- 普通验证与后置验证共用 capability check 转换和 fixture 物化逻辑；
- Verifier 将“无 fixture 的构建/原测试”和“有 fixture 的能力检查”拆开复用，避免后置测试被重复执行或误判成原测试回归。

## 刻意保留的相似代码

### BaselineVerifier 与候选 Verifier

二者都会执行构建和原测试，但输出模型和失败含义不同：原仓库失败统一记为 `BASELINE_FAILED`，候选失败需要区分 `BUILD_FAILED` 与 `REGRESSION_FAILED` 并参与 Agent 路由。当前保留两个短入口比引入带模式参数的通用函数更清楚。

### 首次生成循环与 repair 循环

两个循环都有 Transformer、Reviewer 和确定性验证，但状态语义不同。首次生成允许 Reviewer 将分类问题退回 Analyzer；`repair` 必须复用已有候选，且不得重新运行 Analyzer。二者只共享无状态步骤，不合并状态机，避免一个布尔参数改变研究流程。

### materialized_verification_fixtures

该函数只是已有调用方的兼容入口，实际复制和清理工作已经委托给通用 `materialized_fixtures`，不包含第二份实现。

## 剩余维护风险

`consensus_seam/workflow.py` 目前是最大的 Python 文件。它的主要体积来自显式状态转移和失败路由，不属于同代码块复制；消息捕获与注入共享一次 Transformer 调用，其余能力仍复用同一逐项循环，没有新增第二套编排。如果以后增加第五种工作流，应优先按“首次生成”和“生成后修复”拆分编排模块，而不是继续扩展该文件。

## 验证

- `pytest`：69 项通过；
- `git diff --check`：通过；
- `python3 -m compileall -q consensus_seam`：通过；
- 当前生产 Python 文件共 5153 个物理行，其中 `workflow.py` 为 1085 行。
