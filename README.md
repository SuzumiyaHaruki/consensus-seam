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

一条路径表示测试方通过一组一致的公开输入输出边界、缓存或目标所有权和控制方式驱动系统。不同公开节点 API、输入输出边界或同步/异步控制面通常是不同路径；消息类型、helper、文件和到达同一控制面的内部条件分支不是不同路径。

## 三个 Agent 与控制器

1. Agent 1 只读分析七项能力、真实代码边界和限制。
2. Agent 2 只修改被判定为 `PATCHABLE` 且被本次实验选中的能力。
3. Agent 3 独立、只读地审查修改范围、接口可用性和声明一致性。
4. Controller 负责固定流程、隔离工作树、构建、原测试和项目配置的基础能力检查。

Agent 3 发现违反能力合同、路径覆盖声明或接口报告的问题时，必须通过 `REVISE_AGENT1` 或 `REVISE_AGENT2` 自动反馈；只有不妨碍合同成立的剩余限制才能保留在 `PASS.risks`。Agent 2 修订发生在重新应用上一版候选的 fresh worktree 中，不需要人工提供测试或重新从空白生成。

全局能力规范只描述测试行为，不规定统一 Go API。传输抽象、节点类型、节点注册表、缓存结构和函数名都由目标决定。

Analyzer 必须区分“底层原语存在”和“测试接口完整存在”。消息捕获要求受控输出在投递前进入测试可见缓存，并提供枚举、`Take`、`Drop` 和 `Clear`；一次性输出、channel、投递后日志和普通输入函数都只是原语。实例引用要么仍命中测试方观察到的实例，要么明确报告过期，不能静默指向另一实例；不要求永久数字 ID。

消息捕获和注入使用同一组端到端路径逐条分析，连续的发送端和接收端边界不能拆成两条，也不能用 A 路径的捕获和 B 路径的注入拼成完整支持。受控捕获点必须拥有继续传递权，不能与协议消费者竞争读取。注入可以采用分离式 `Take + ProtocolInput`，也可以采用组合式单调用；后者不默认承诺事务原子性。请求必须进入正常请求处理入口，完成响应不能代替请求注入。请求—响应或 future 路径还必须保留原有完成机制，不能让发送方、响应 channel 或 future 静默失联。选择、调度、重试和断言仍由测试方负责。

Go 结构体按值复制不能自动证明快照安全，Agent 还要检查嵌套 slice、map、pointer、interface、channel、future 和可消费流。随机性控制必须在相同初始状态、控制参数和测试调度下重现每个实例的选择序列，并让测试方知道每次实际选择值；选择可以随决策变化，不要求固定常量或每实例随机源。

时间控制的低侵入按语义而不是文件数量判断：没有 Tick、调用点分散或需要修改多个文件都不自动等于 `INVASIVE`。能够通过 Clock/Timer 注入保持生产默认、timer 顺序和协议转换条件时，应判为 `PATCHABLE`；只有必须重设计调度或协议语义时才拒绝修改。

低侵入改造可以是复用、包装、hook、依赖注入、配置项、只读 accessor 或扩展现有测试 harness。生命周期要求 crash 时停止活动并丢弃易失运行实例，只保留目标已经持久化的状态；restart 必须从正常恢复入口构造新实例。pause/resume、优雅停止、网络断连或分区不能替代 crash/restart。Seam 不发明持久化语义，也不实现恢复后的协议追赶。外部输入只包括应用提案、读请求、事务和复制的成员变更，不把诊断、barrier、snapshot/restore、bootstrap 或领导权转移混入工作负载清单。

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
├── presentation/                      # 展示材料
│   ├── ConsensusSeam_etcd实验展示.pdf # 当前架构与 etcd 实验展示
│   └── generate_demo_pdf.py           # ReportLab 可重复生成脚本
├── tests/                             # Controller 测试，不是目标协议测试
│   ├── unit/                          # 模型、配置、Prompt、路由、LLM、工具、报告
│   ├── integration/                   # 工作流、worktree、Go 符号、fixture、修订闭环
│   └── helpers.py                     # 测试共享构造辅助
├── runs/                              # 实验产物
│   ├── <run-id>/                      # 完整本地运行、日志和临时信息；Git 忽略
│   └── latest/                        # 最近一次可审计小型产物；Git 跟踪
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

HashiCorp Raft `v1.7.3` 第一阶段接口生成：

```bash
consensus-seam patch \
  --project evaluation/hashicorp-raft/project.yaml \
  --api-key-file /绝对路径/deepseek-key.txt \
  --model-profile manifest
```

运行所需材料见 [docs/required-materials.md](docs/required-materials.md)，本轮 Python 冗余审计见 [docs/redundancy-audit.md](docs/redundancy-audit.md)。
