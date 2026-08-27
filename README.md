# ConsensusSeam v0.1

ConsensusSeam 是一个面向 Go 共识实现的多 Agent 测试接口分析与补充框架。

它研究的问题是：

> 在只提供目标源码、构建测试命令和系统边界的情况下，多 Agent 能否识别共识系统已有的测试控制能力，并通过小规模、低侵入修改补充缺失接口？

ConsensusSeam 不生成测试策略，也不决定何时丢包、重启节点或推进时间。它只负责让这些动作具备可调用的接口。

## v0.1 的七项能力

1. 消息捕获（`message_capture`）
2. 消息注入（`message_injection`）
3. 时间控制（`time_control`）
4. 随机性控制（`randomness_control`）
5. 生命周期控制（`lifecycle_control`）
6. 状态观察（`observation`）
7. 外部输入发现（`external_input`）

Agent 1 对每项能力保留原有六种分类：

- `SUPPORTED`：目标系统已经完整提供；
- `PATCHABLE`：缺失，但可以低侵入补充；
- `PARTIAL`：已有部分能力，但不完整；
- `INVASIVE`：实现它需要改变核心语义或作出目标系统尚未定义的决定；
- `UNKNOWN`：源码证据不足，无法可靠判断；
- `NOT_APPLICABLE`：相对于本次系统边界不适用。

人工只定义系统边界，不需要预先知道目标有哪些实现路径。Agent 1 应从源码中发现边界内所有实质不同的路径，例如同步/异步执行方式、不同节点抽象或不同消息出口；Agent 2 应尽可能覆盖所有能够低侵入实现的路径。确实无法安全覆盖的路径必须在报告中说明，不能静默忽略。

“实质不同的路径”指输入边界、输出边界或控制方式不同的公开运行路径，不是要求枚举协议内部每一个条件分支。

## 三个 Agent 与控制器

1. Agent 1 只读分析七项能力、真实代码边界和限制。
2. Agent 2 只修改被判定为 `PATCHABLE` 且被本次实验选中的能力。
3. Agent 3 独立、只读地审查修改范围、接口可用性和声明一致性。
4. Controller 负责固定流程、隔离工作树、构建、原测试和项目配置的基础能力检查。

Agent 3 发现违反能力合同、路径覆盖声明或接口报告的问题时，必须通过 `REVISE_AGENT1` 或 `REVISE_AGENT2` 自动反馈；只有不妨碍合同成立的剩余限制才能保留在 `PASS.risks`。Agent 2 修订发生在重新应用上一版候选的 fresh worktree 中，不需要人工提供测试或重新从空白生成。

全局能力规范只描述行为，不规定所有目标必须使用相同的语言接口。某种传输抽象、节点类型或节点注册表只能是具体目标的实现选择，不能成为通用前提。

Analyzer 必须区分“底层原语存在”和“测试接口完整存在”。一次性消息输出、channel 交付、发送 hook、内部队列或正常协议输入函数都只是原语；即使测试方可以自行把输出复制到新切片，也不能据此声称目标已经提供缓存。Agent 必须从源码发现目标实际存在的重要路径，每条声明支持的路径都要有测试可控的显式缓存，并明确指定缓存实例与正常输入入口的关系。目标已有队列、记录、下标、handle 或可选控制 ID 都可以成为引用形式；全局合同规定功能，不预设路径数量、统一 API 形状或数字 ID。

低侵入改造可以是包装、hook、依赖注入、配置项、只读 accessor 或扩展目标已有测试 harness。消息控制必须最终形成一个目标原生的缓存控制面，但可以直接扩展已有缓存而不建立平行存储，也不要求固定类型或方法名。只有所有已发现路径都已经具备完整控制面时才是 `SUPPORTED`；只要某条路径仍要求测试方自行保存消息或自行拼接缓存与输入原语，就应在可低侵入补充时标为 `PATCHABLE`。

## v0.1 不追求什么

- 不证明共识协议整体正确；
- 不为任意系统生成完备测试；
- 不实现测试调度策略或模糊测试器；
- 不要求覆盖所有同步、异步、持久化和部署组合；
- 不发明目标系统没有定义的崩溃恢复语义；
- 不把单个目标实验暴露的特殊情况自动升级为全局强制合同。

七项能力的统一说明见 [docs/capabilities.md](docs/capabilities.md)，完整非目标见 [CODEX_SPEC.md](CODEX_SPEC.md)，设计边界见 [docs/design-analysis.md](docs/design-analysis.md)。

## 环境要求

- Python 3.10 或更高版本；
- Git；
- Go（分析或修改 Go 目标时）。

项目不强制 Python 3.12，以本机可用的 Python 3.10+ 为准。

## 安装与测试

```bash
cd /home/nitro/Desktop/consensus-seam
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest
```

如果 Ubuntu/Debian 缺少 `venv`：

```bash
sudo apt install python3-venv
```

## 运行方式

API 密钥应放在仓库之外。可以通过环境变量提供：

```bash
export DEEPSEEK_API_KEY='...'
consensus-seam analyze --project /绝对路径/project.yaml
```

也可以把纯密钥放在单独文本文件中：

```bash
consensus-seam analyze \
  --project /绝对路径/project.yaml \
  --api-key-file /绝对路径/deepseek-key.txt \
  --model-profile manifest
```

`DEEPSEEK_API_KEY_FILE` 可以提供同一路径，`DEEPSEEK_BASE_URL` 可以指定兼容网关。密钥内容不会写入实验产物。

四个主命令分别是：

```bash
consensus-seam analyze --project /绝对路径/project.yaml
consensus-seam patch   --project /绝对路径/project.yaml
consensus-seam run     --project /绝对路径/project.yaml
consensus-seam repair  --project /绝对路径/project.yaml \
  --run /绝对路径/runs/<原生成实验> \
  --checks /绝对路径/post-hoc-checks.yaml
```

- `analyze`：只运行 Agent 1，不修改源码，也不执行目标构建测试；
- `patch`：运行三个 Agent和候选构建，不执行完整原测试或 evaluator-only 隐藏检查；
- `run`：预配置评测/回归模式；适用于已经在目标 manifest 中提供稳定 capability checks 的目标，在重新生成候选后执行 baseline、原测试和确定性检查。
- `repair`：可选的质量增强流程；不重新运行 Analyzer，读取已有候选补丁和接口报告，执行生成后编写的后置测试，并把确定性失败反馈给 Agent 2 修复。

`--responses responses.json` 是无 API 密钥时使用的确定性开发适配器。JSON 中按顺序存放 Agent 原始响应。

## 工具与修改边界

- Analyzer 可以列目录、读文件、搜索文本和查询 Go 声明，不能编辑源码或运行目标测试。
- Transformer 只能编辑隔离 Git worktree，并受有限的 `apply_patch`/`write_file` 操作约束。
- Reviewer 分别读取原始和修改后的代码，不能写文件。
- Agent 2 可以新增 `*_test.go`，但不能修改目标仓库已有的 Go 测试。
- 如果 Agent 2 在实现阶段发现能力需要侵入式修改，可以报告 `INVASIVE_REDISCOVERED`；该候选 worktree 会被丢弃。

这些安全措施用于隔离修改和保持实验可审计，不代表框架已经验证了所有目标语义。

## 验证原则

第一版按命令提供不同验证强度：

1. `patch` 要求候选能够格式化、构建，并通过 Reviewer；这是未知目标接口生成的完成条件；
2. `run` 额外要求未修改目标通过 baseline、候选通过原测试，并执行预先配置的基础能力检查；
3. `repair` 对已有候选执行生成后提供的真实使用检查，并在失败时进行可选修复。

`run` 不适用于尚不知道接口形状、也没有预配置 checks 的首次目标。某个成熟目标可以配置更多回归检查，但这些目标专属检查必须留在自己的 `evaluation/<target>/` 目录，不能反向变成所有共识系统的全局要求。

开放式接口生成不要求预先猜测 API。`patch` 是完整的主流程，结束后已经得到接口代码、接口报告和使用说明，不运行 `repair` 也可以使用这些结果。如果还希望用真实使用场景提高候选质量，可以根据实际 `USAGE.md` 编写测试，并通过 `repair --checks` 启动独立修复循环。后置测试代码直到 Reviewer 返回后才进入候选 worktree；Agent 2 只看到失败类型、命令和输出，不直接读取 evaluator-only fixture。

实验失败分为三类：

- 通用框架错误：修改 ConsensusSeam；
- 目标项目限制：记录在该目标报告中；
- v0.1 范围之外：明确记录，不继续膨胀全局规范。

## 实验产物

每次运行写入 `runs/<run-id>/`。目标原仓库不会被 Agent 2 直接修改；候选代码位于独立 worktree。

主要产物包括：

- `capability-report.json`：七项能力分类、证据和限制；
- `interface-report.json`：Agent 2 实际补充的接口；
- `USAGE.md`：面向测试方的简洁接口矩阵、调用入口、示例和剩余限制；
- `AUDIT.md`：修改前分析、路径证据、实现方式和 Reviewer 结论的完整审计说明；
- `changes.patch`：最终候选修改；
- `review-report.json`：Agent 3 审查；
- `verification-report.json`：构建、原测试和能力检查；
- `patch-metrics.json`：修改文件和代码行规模；
- `agent-run-stats.json`、`tool-call-audit.json`：模型和工具成本审计；
- `unresolved.json`：未实现或被实验范围跳过的能力。

完成后，适合审计的小型产物会复制到 Git 跟踪的 `runs/latest/`，覆盖上一次导出。完整 patched worktree 不会进入 Git。框架不会自动提交、推送或把补丁应用到目标仓库。

## 评测材料与人工 ground truth

正式评测材料位于 `evaluation/`，不在目标仓库的 Agent 工具范围内。

- 隐藏测试只在 Reviewer 完成后临时复制进候选 worktree；
- 人工 ground truth 只用于实验结束后的准确性评估；
- ground truth 不进入 Agent Prompt，也不参与实际接口生成。

因此，工程运行不要求每个新目标先提供一份人工标准答案。

## 当前目标

Mini Raft 预配置回归评测：

```bash
consensus-seam run \
  --project evaluation/mini-raft/project.yaml \
  --api-key-file /绝对路径/deepseek-key.txt \
  --model-profile manifest
```

etcd/raft 第一阶段接口生成：

```bash
GOTOOLCHAIN=auto consensus-seam patch \
  --project evaluation/etcd-raft/project.yaml \
  --api-key-file /绝对路径/deepseek-key.txt \
  --model-profile manifest
```

运行所需材料见 [docs/required-materials.md](docs/required-materials.md)，本轮 Python 冗余审计见 [docs/redundancy-audit.md](docs/redundancy-audit.md)。
