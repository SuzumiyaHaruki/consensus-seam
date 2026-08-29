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

v0.1 明确只面向 Go 共识实现。人工只定义系统边界，不需要预先知道目标有哪些实现路径。Agent 1 从源码发现边界内所有实质不同的公开路径；Agent 2 必须覆盖所有能够通过缓存、薄包装、hook 或依赖注入低侵入完成的路径，不能只实现最方便或项目自用测试的一条。确实需要改变协议语义的路径才保留为未覆盖并说明原因。

一条路径表示测试方通过一组一致的公开输入输出边界、缓存或目标所有权和控制方式驱动系统。不同公开节点 API、输入输出边界或同步/异步控制面通常是不同路径；消息类型、timer 位置、随机调用点、helper、文件和到达同一控制面的内部条件分支不是不同路径。路径必须从测试方能够构造或调用的公开控制面开始。

## 三个 Agent 与控制器

1. Agent 1 只读分析七项能力、真实代码边界和限制。
2. Agent 2 只修改被判定为 `PATCHABLE` 且被本次实验选中的能力。
3. Agent 3 独立、只读地审查修改范围、接口可用性和声明一致性。
4. Controller 负责固定流程、隔离工作树、构建、原测试和项目配置的基础能力检查。

Agent 3 发现违反能力合同、路径覆盖声明或接口报告的问题时，必须通过 `REVISE_AGENT1` 或 `REVISE_AGENT2` 自动反馈；只有不妨碍合同成立的剩余限制才能保留在 `PASS.risks`。Agent 2 修订发生在重新应用上一版候选的 fresh worktree 中，不需要人工提供测试或重新从空白生成。

能力规范固定测试方需要调用的名称、结构和语义，同时保留目标内部实现自由。
例如消息统一使用 `MessageController`、`PendingMessage`、不透明
`MessageHandle` 以及 `Pending`、`Drop`、`Clear`、`Inject`；时间、随机性和
生命周期分别使用 `TimeController`、`RandomController` 和
`LifecycleController`。节点 ID、原生消息、随机值和状态仍使用目标的具体
导出类型，不能把类型槽名称原样生成，也不能退化成裸 `any`。

Analyzer 必须区分底层原语与完整测试接口。消息控制要求边界内请求、响应和
单向消息在投递前进入同一个 Controller 缓存，捕获和注入逐条覆盖同一组
端到端路径。`Pending` 返回深拷贝快照，`Inject` 使用 Controller 私有副本并
在正常输入边界确认接受后移除消息；v0.1 不提供 `Take`、消息修改、重定向、
复制或凭空构造。选择、调度、重试和断言仍由测试方负责。

时间控制通过系统级 `Advance` 手动推进所有运行节点；随机性通过 seed 重现
可变化的选择序列并记录实际语义值。生命周期明确区分 Pause/Resume、正常
Stop、突然 Crash 和 Restart；窄且默认关闭的核心 hook 可以低侵入实现，
会改变协议或持久化语义的操作则公开返回 `ErrLifecycleUnsupported`。时间和
随机控制必须在异步运行开始前安装；Restart 必须更新所有 Controller 的运行
实例绑定；Crash 返回后旧执行上下文不能继续修改状态或存储。外部输入
只做已有工作入口发现，状态观察优先复用安全的目标原生类型化接口。完整
合同和逐项边界见 `docs/capabilities.md`。

## 目录架构

主要数据流如下：

```text
project.yaml + spec/ + prompts/
              ↓
      consensus_seam/cli.py
              ↓
    consensus_seam/workflow.py
              ↓
 Agent 1 → Agent 2 worktree → Agent 3
              ↓
     verify/ + reporting.py
              ↓
         runs/<run-id>/
```

仓库结构：

```text
consensus-seam/                         # 仓库根目录
├── consensus_seam/                    # Python Controller 与三个 Agent 的实现
│   ├── agents/                        # 严格隔离的 Agent 角色
│   │   ├── base.py                    # Prompt 组装、结构化输出与校验重试
│   │   ├── analyzer.py                # Agent 1：只读能力分析
│   │   ├── transformer.py             # Agent 2：隔离 worktree 中低侵入修改
│   │   └── reviewer.py                # Agent 3：独立只读审查与反馈路由
│   ├── languages/                     # 目标语言后端；v0.1 只支持 Go
│   │   ├── base.py                    # Verifier/workspace 共用语言边界
│   │   ├── go.py                      # Go 格式化、构建辅助和符号查询
│   │   └── go_ast/main.go             # Go AST 声明、方法和引用定位工具
│   ├── llm/                           # 模型供应商与工具循环
│   │   ├── base.py                    # 与供应商无关的最小 LLM 接口
│   │   ├── client.py                  # 确定性/占位 Client
│   │   ├── deepseek.py                # DeepSeek Chat Completions HTTP 传输
│   │   ├── profiles.py                # manifest/CLI 模型配置合并
│   │   └── runtime.py                 # 三个角色共用的有界工具调用循环
│   ├── verify/                        # 不依赖 Agent 自我声明的确定性验证
│   │   ├── baseline.py                # 干净目标 revision 的 baseline
│   │   ├── capability.py              # 项目专属能力检查及失败码
│   │   ├── fixtures.py                # Reviewer 后注入 evaluator-only fixture
│   │   └── verifier.py                # 格式化、构建、原测试和能力检查执行
│   ├── cli.py                         # analyze/patch/run/repair 命令入口
│   ├── workflow.py                    # Agent、修订、验证和产物的显式状态机
│   ├── models.py                      # Pydantic 数据合同、枚举与跨字段校验
│   ├── config.py                      # project/spec/policy/protocol 加载与边界校验
│   ├── routing.py                     # 固定失败和 Reviewer 反馈路由
│   ├── workspace.py                   # 隔离 Git worktree 生命周期
│   ├── tools.py                       # 按角色限制读、搜索、补丁和命令工具
│   ├── reporting.py                   # JSON、USAGE、AUDIT、统计和 latest 输出
│   ├── resources.py                   # 源码/wheel 中定位 prompts 与 spec
│   └── __main__.py                    # python -m consensus_seam 入口
├── prompts/                           # 提供给 Agent 的英文行为要求
│   ├── agent1.md                      # 证据、路径发现和能力分类
│   ├── agent2.md                      # 低侵入实现、消息闭环和最少测试
│   └── agent3.md                      # 逐路径审查、完成机制和问题路由
├── spec/                              # 目标无关能力与修改合同
│   ├── capabilities.yaml              # 七项能力英文合同
│   ├── modification-policy.yaml       # Agent 2 允许/禁止的修改
│   └── protocols/raft.yaml            # Raft 概念简介，不是 ground truth
├── evaluation/                        # 目标专属正式实验输入
│   ├── README.md                      # 评测材料和 Agent 可见边界
│   ├── mini-raft/                     # 小型缺口目标与隐藏验收材料
│   │   ├── project.yaml               # 预配置 run 项目清单
│   │   ├── human-ground-truth.yaml    # 运行后独立评估，不进入 Prompt
│   │   └── hidden-acceptance/         # Reviewer 后才注入的目标测试
│   ├── etcd-raft/                     # etcd/raft 3.6 盲 patch 目标
│   │   ├── project.yaml               # 仓库、边界、命令和模型配置
│   │   └── README.md                  # 固定 revision 与运行说明
│   └── hashicorp-raft/                # HashiCorp Raft v1.7.3 对照目标
│       ├── project.yaml               # 真实时间/异步运行盲 patch 配置
│       └── README.md                  # 固定 revision、边界与基线说明
├── targets/                           # 新目标接入模板
│   └── examples/
│       ├── project.yaml.example       # 最小项目清单示例
│       └── post-hoc-checks.yaml.example # repair 检查示例
├── docs/                              # 面向使用者的中文说明
│   ├── capabilities.md                # 七项能力合同
│   ├── design-analysis.md             # 研究目标、路径、分工和 repair 边界
│   ├── required-materials.md          # 新目标与正式实验所需材料
│   └── redundancy-audit.md            # Python 冗余审计与清理记录
├── tests/                             # Controller 测试，不是目标协议测试
│   ├── unit/                          # 模型、配置、Prompt、路由、LLM、工具、报告
│   ├── integration/                   # 工作流、worktree、Go 符号、fixture、修订闭环
│   └── helpers.py                     # 测试共享构造辅助
├── runs/                              # 实验产物
│   ├── <run-id>/                      # 完整本地运行、日志和临时信息；Git 忽略
│   └── latest/                        # 各目标最近一次可审计小型产物；Git 跟踪
│       └── <project>/                 # 例如 etcd-raft、mini-raft
├── README.md                          # 项目入口、架构和使用说明
├── CODEX_SPEC.md                      # v0.1 非目标与实现边界
├── pyproject.toml                     # 包、依赖、CLI、wheel 资源和 pytest 配置
├── .gitignore                         # 忽略环境、密钥和除 latest 外的 runs
└── .gitattributes                     # PDF 作为 binary 处理
```

`.venv/`、`.pytest_cache/`、`__pycache__/`、`dist/` 和 `build/` 是本地生成
目录，不属于仓库源码架构，并由 `.gitignore` 忽略。

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
- Agent 2 只能新增验证新行为所需的最少 `*_test.go`，不能修改目标仓库已有测试，也不应重复已有覆盖或生成大规模参数组合。
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

完成后，适合审计的小型产物会复制到 Git 跟踪的
`runs/latest/<project>/`，只覆盖同一目标的上一次导出，其他目标的 latest
保持不变。完整 patched worktree 不会进入 Git。框架不会自动提交、推送或
把补丁应用到目标仓库。

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

HashiCorp Raft `v1.7.3` 第一阶段接口生成：

```bash
consensus-seam patch \
  --project evaluation/hashicorp-raft/project.yaml \
  --api-key-file /绝对路径/deepseek-key.txt \
  --model-profile manifest
```

运行所需材料见 [docs/required-materials.md](docs/required-materials.md)，本轮 Python 冗余审计见 [docs/redundancy-audit.md](docs/redundancy-audit.md)。
