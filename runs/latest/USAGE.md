# etcd-raft 测试接口使用报告

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
能力状态、源码证据和完整限制以 `capability-report.json` 为准。

## 消息捕获

- 分析状态：`PATCHABLE`
- 覆盖边界：协议输出点为 Ready.Messages（以及 AsyncStorageWrites 下内嵌于 MsgStorageAppend.Responses 的对等消息）；捕获发生在 Ready 边界与 rafttest 的 env.Messages/AppendWork/ApplyWork 存储处；真实网络发送在边界外。
- 现有测试接口是否完整：否
- 测试支持判断：env.Messages 已是真实 pending 存储且捕获后不会自动继续，但契约要求可调用入口按稳定消息 ID 列出（含 sender/receiver/type/捕获顺序）并可清空；现有接口既无稳定控制面 ID 也无 list/clear 入口，属于低侵入即可补齐的测试面缺口。

### Analyzer 发现的实现路径

- RawNode 同步路径：输出点为 Ready().Messages（readyWithoutAccept rawnode.go:141-189），消息不会自动继续，continuation 是应用发送后调用 Advance；suppression 点是应用不发送（acceptReady 在 rawnode.go:433 清空 r.msgs）。仅有捕获原语，无带 ID 的 pending 存储。
- Node 异步路径：输出点为 Ready 通道（node.go:440 readyc <- rd），捕获点在应用侧接收 Ready 处；消息同样不自动继续。
- AsyncStorageWrites 路径：对等输出内嵌于 MsgStorageAppend.Responses（rawnode.go:257），经 MsgStorageAppendResp/ApplyResp 回注状态机；rafttest 中响应消息在 ProcessAppendThread 处理后才汇入 env.Messages（interaction_env_handler_process_append_thread.go:77）。
- rafttest InteractionEnv 路径：ProcessReady 捕获非本地消息到 env.Messages（保持捕获顺序、sender/receiver/type 可用），本地存储消息分别进入 AppendWork/ApplyWork；投递/丢弃由 DeliverMsgs 显式触发，捕获后不自动继续。

### 建议改造

- 在 rafttest InteractionEnv 之上增加捕获层：为 env.Messages 中每条消息分配稳定控制面 ID，提供 ListPending()/ClearPending() 及对应数据驱动命令。
- 为 RawNode/Node 路径提供包装：在 Ready()/ProcessReady 处接管 rd.Messages 存入带 ID 的 pending 存储，阻止自动发送，由测试控制是否 Advance。
- AsyncStorageWrites 路径：在 ProcessAppendThread 处理 Responses 时（现 interaction_env_handler_process_append_thread.go:77）同步登记 ID。

### 目标已有入口

- `RawNode.Ready (rawnode.go:133)`
- `RawNode.Advance (rawnode.go:482)`
- `Node.Ready 通道 (node.go:552)`
- `rafttest InteractionEnv.ProcessReady (interaction_env_handler_process_ready.go:45)`
- `rafttest InteractionEnv.ProcessAppendThread (interaction_env_handler_process_append_thread.go:47)`
- `rafttest InteractionEnv.Messages 字段 (interaction_env.go:52)`

### 限制

- 真实网络发送在系统边界外；库只输出 Ready.Messages，从不自行发送。
- Node 路径的 Ready 经通道异步交付，捕获点在应用侧。
- AsyncStorageWrites 下对等输出内嵌于本地存储消息的 Responses，需先处理本地存储线程才可见。

## 消息注入

- 分析状态：`PATCHABLE`
- 覆盖边界：注入通过目标节点的正常协议输入入口（RawNode.Step / node.Step，最终进入 raft.Step）完成，不直接改写协议状态；目标绑定为 rafttest Node 切片中真实持有的 *raft.RawNode 或调用方持有的 Node/RawNode 对象引用。
- 现有测试接口是否完整：否
- 测试支持判断：真实目标绑定与投递原语齐备（对象切片 + Step），但现有 DeliverMsgs 按接收者+类型批量投递，无法按稳定控制面 ID 精确选择并只消费一条消息，缺一个低侵入的按 ID 注入入口。

### Analyzer 发现的实现路径

- RawNode 同步路径：测试持有 *RawNode 引用，调用 rn.Step(m) 同步注入；目标绑定为直接对象引用；缺少按稳定 ID 从 pending 存储单选消息的协调层。
- Node 异步路径：node.Step(ctx, m) 将消息送入 recvc 通道，由 run() 循环处理（node.go:399-404），注入为异步、无同步错误返回；消息内容原样保留。
- rafttest 路径：DeliverMsgs 按接收者+类型（或丢弃）匹配 env.Messages 中的消息，同步调用目标节点 Step；目标绑定为 env.Nodes[msg.To-1].RawNode（真实对象，按 To 路由）。
- AsyncStorageWrites 路径：本地存储响应消息（MsgStorageAppendResp/ApplyResp）经 Step 回注，属于既有协议输入路径，无需另行注入。

### 建议改造

- 在捕获层提供 Inject(id)/Deliver(id)：按 ID 取出单条消息，同步调用 env.Nodes[msg.To-1].Step(msg) 投递，投递后从 pending 存储移除，并声明 ID 属于 pending 存储作用域。
- 为 Node 路径提供基于 ID 的注入：通过 node.Step(ctx, m)（异步）投递，保持 sender/receiver/content 不变。

### 目标已有入口

- `RawNode.Step (rawnode.go:118)`
- `Node.Step (node.go:478)`
- `rafttest InteractionEnv.DeliverMsgs (interaction_env_handler_deliver_msgs.go:81)`
- `rafttest InteractionEnv.Nodes（真实 RawNode 持有者，interaction_env.go:37）`

### 限制

- Node 路径注入为异步（recvc 通道），无同步错误返回。
- RawNode.Step / node.Step 会拒绝本地消息类型（IsLocalMsg 检查，rawnode.go:120），注入范围限定为对等协议消息。
- 目标 ID 本身不是目标绑定；现有绑定来自 env.Nodes 切片持有的真实 RawNode 对象。

## 时间控制

- 分析状态：`SUPPORTED`
- 覆盖边界：协议时间完全由显式 Tick 驱动：tick 计数推进 electionElapsed/heartbeatElapsed，选举与心跳超时以 tick 为单位；库的非测试代码不读取墙钟。
- 现有测试接口是否完整：是
- 测试支持判断：显式 Tick 入口在 RawNode、Node 与 rafttest 三层均可直接调用，协议内无墙钟使用，无需时钟注入即可确定性推进时间。

### Analyzer 发现的实现路径

- RawNode 同步路径：Tick() 直接调用 raft.tick()（tickElection/tickHeartbeat），测试可逐 tick 推进。
- Node 异步路径：Tick() 向缓冲 tickc 通道发送（容量 128），由 run() 循环消费并调用 n.rn.Tick()（node.go:438-439）。
- rafttest 路径：Tick(idx, num) 循环调用节点 Tick，tick-election/tick-heartbeat 命令按配置的 ElectionTick/HeartbeatTick 推进。

### 目标已有入口

- `RawNode.Tick (rawnode.go:64)`
- `RawNode.TickQuiesced (rawnode.go:78，已废弃)`
- `Node.Tick (node.go:463)`
- `rafttest Tick / tick-election / tick-heartbeat (interaction_env_handler_tick.go:34)`

### 限制

- TickQuiesced（rawnode.go:78）已废弃，不应用于新测试。
- Node.Tick 在 run 循环繁忙时可能丢弃 tick 并仅告警（node.go:467-469）。
- ReadOnlyLeaseBased 依赖应用层时钟漂移假设（raft.go:63-67），时钟本身在系统边界外。

## 随机性控制

- 分析状态：`PATCHABLE`
- 覆盖边界：协议相关随机性仅体现在 randomizedElectionTimeout（electionTimeout 到 2*electionTimeout-1），来源为包级 globalRand 的 crypto/rand，抽取点在 resetRandomizedElectionTimeout。
- 现有测试接口是否完整：否
- 测试支持判断：现有钩子+处理器只能固定单个随机值，且依赖测试二进制内的导出函数与 InteractionOpts 管道；随机源本身不可播种，状态转换后固定值失效，测试接口不完整。

### Analyzer 发现的实现路径

- RawNode 路径：randomizedElectionTimeout 在 reset() 时由 globalRand.Intn 抽取，tickElection 经 pastElectionTimeout 触发选举；测试只能通过测试二进制内的 SetRandomizedElectionTimeout 改写。
- Node 路径：同一状态机字段，经 Tick 通道驱动，无额外随机源。
- rafttest 路径：set-randomized-election-timeout 命令在状态转换前固定超时值，状态转换后失效（reset 重新抽取）。

### 建议改造

- 为 Config 增加可选的随机源/种子字段（如 RandSeed 或 rand 源），newRaft 时构造 r.rand，resetRandomizedElectionTimeout 改用 r.rand.Intn，默认回退 crypto/rand；低侵入且不替换算法。
- 或保留现有钩子并文档化其测试二进制限定与状态转换重置行为，为 RawNode 提供同等测试构造器。

### 目标已有入口

- `raft.resetRandomizedElectionTimeout (raft.go:2049)`
- `raft.globalRand (raft.go:102)`
- `raft.SetRandomizedElectionTimeout（测试文件导出，raft_test.go:4098）`
- `rafttest set-randomized-election-timeout 处理器 (interaction_env_handler_set_randomized_election_timeout.go:24)`

### 限制

- 随机化超时在每次状态转换的 reset() 中重新抽取（raft.go:793），固定值在转换后失效。
- SetRandomizedElectionTimeout 定义在 raft_test.go（测试文件），模块外部使用者无法导入。

## 生命周期控制

- 分析状态：`SUPPORTED`
- 覆盖边界：生命周期控制限定在协议库内：Node.Stop 停止 goroutine，StartNode/RestartNode/NewRawNode 创建节点，RestartNode 从 Storage 恢复；崩溃后状态存活与否由既有 HardState/SoftState/unstable 与 Storage 语义定义，未发明新的持久/易失划分。
- 现有测试接口是否完整：是
- 测试支持判断：创建、停止、恢复 API 均为公开接口，测试可直接组合（例如用同一 MemoryStorage 先后 RestartNode 模拟重启）；未发明持久/易失划分。

### Analyzer 发现的实现路径

- RawNode 同步路径：NewRawNode/Bootstrap 构造，无 goroutine、无 Stop，生命周期由调用方同步控制。
- Node 异步路径：StartNode/RestartNode 启动 run() 事件循环，Node.Stop 关闭 done 并阻塞至循环退出（node.go:336-346）。
- 恢复路径：RestartNode 从同一 Storage 重建 RawNode，newRaft 读取 InitialState（raft.go:442）并经 loadState（raft.go:2033）恢复 HardState 与日志。
- rafttest 路径：AddNodes 以 MemoryStorage+快照创建 RawNode，未提供停止操作（RawNode 无 goroutine）。

### 目标已有入口

- `NewRawNode (rawnode.go:51)`
- `RawNode.Bootstrap (bootstrap.go:30)`
- `StartNode (node.go:276)`
- `RestartNode (node.go:286)`
- `Node.Stop (node.go:336)`
- `rafttest InteractionEnv.AddNodes (interaction_env_handler_add_nodes.go:94)`

### 限制

- 真实磁盘/WAL 持久化在系统边界外，崩溃恢复的物理持久性依赖应用提供的 Storage。
- rafttest 的 ProcessReady 注释明确尚未支持崩溃模拟（interaction_env_handler_process_ready.go:46）。
- RawNode 无停止语义（同步对象、无后台 goroutine）。

## 状态观察

- 分析状态：`SUPPORTED`
- 覆盖边界：观察量为协议库内节点/全局状态：role（SoftState.RaftState）、term/vote/commit（HardState）、applied、日志范围与 Progress；全部通过只读访问器暴露，不创建协议状态。
- 现有测试接口是否完整：是
- 测试支持判断：现有 Status/BasicStatus/WithProgress 与 rafttest 输出命令直接满足观察契约（role/term/commit/applied/log range），无需新增目标代码。

### Analyzer 发现的实现路径

- RawNode 同步路径：Status()/BasicStatus()/WithProgress() 同步返回状态快照。
- Node 异步路径：Status() 经 status 通道由 run() 循环内的 getStatus 应答（node.go:452-453）。
- rafttest 路径：status 命令打印 Progress 映射，raft-log 命令经 Storage.Entries 打印日志范围，raft-state 命令打印各节点 role/term/lead。

### 目标已有入口

- `RawNode.Status (rawnode.go:498)`
- `RawNode.BasicStatus (rawnode.go:505)`
- `RawNode.WithProgress (rawnode.go:521)`
- `Node.Status (node.go:574)`
- `rafttest Status / RaftLog / handleRaftState 处理器`

### 限制

- Progress 仅在 leader 填充（status.go:25-30）。
- rafttest 的 Status 处理器目前只打印 Progress 映射（interaction_env_handler_status.go:34 TODO）。

## 外部输入

- 分析状态：`SUPPORTED`
- 覆盖边界：系统边界为 go.etcd.io/raft/v3 协议库。外部输入指来自应用的工作负载请求（提案、成员变更、读请求），经 RawNode/Node 的公开方法进入状态机；Step 对等协议入口、Tick 计时器与内部回调不属于外部输入。
- 现有测试接口是否完整：是
- 测试支持判断：现有公开 API 已直接覆盖提案、成员变更与读请求入口，无需新增目标代码；testing_contract 为空。

### Analyzer 发现的实现路径

- RawNode 同步路径：Propose/ProposeConfChange/ReadIndex 构造 pb.Message 后同步调用 raft.Step 进入状态机。
- Node 异步事件循环路径：Propose 经 propc 通道（node.go:391-398），ReadIndex 等经 step 走 recvc 或 propc，由 run() 循环处理。
- rafttest 数据驱动路径：propose / propose-conf-change 命令直接调用节点 RawNode 的 Propose/ProposeConfChange。

### 目标已有入口

- `RawNode.Propose (rawnode.go:90)`
- `RawNode.ProposeConfChange (rawnode.go:101)`
- `RawNode.ReadIndex (rawnode.go:561)`
- `Node.Propose (node.go:474)`
- `Node.ProposeConfChange (node.go:495)`
- `Node.ReadIndex (node.go:613)`
- `rafttest InteractionEnv.Propose / ProposeConfChange`

### 限制

- Campaign（MsgHup）是本地控制消息而非外部工作负载，不计入本能力。
- Node 异步路径中提案可被丢弃或转发给 leader（node.go:391-398 与 ErrProposalDropped），这是既有协议语义。
