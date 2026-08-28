# 七项测试控制能力

ConsensusSeam v0.1 只处理 Go 共识实现。能力规范统一测试方看到的对象、动作
和语义；目标内部采用包装、hook、harness 还是少量核心接缝，由 Agent 根据
源码决定。提供给 Agent 的英文合同以 `spec/capabilities.yaml` 为准。

## 分类与路径

- `SUPPORTED`：原系统已经完整满足合同；
- `PATCHABLE`：可以在不改变协议语义的前提下补齐；
- `PARTIAL`：部分可用，但剩余缺口无法低侵入补齐；
- `INVASIVE`：必须改变协议、持久化、状态转换或顺序语义；
- `UNKNOWN`：源码证据不足；
- `NOT_APPLICABLE`：当前系统边界内不存在该能力对象。

人工只定义 `system_boundary`，不预先指定路径数量。Agent 从源码发现端到端
路径：公开运行对象、输入输出边界、所有权或完成语义不同，通常属于不同
路径；共享同一控制面的消息类型、helper 和内部条件分支不是不同路径。
消息捕获和注入必须逐条覆盖同一组路径，不能用 A 路径的捕获和 B 路径的
注入拼成完整能力。

项目内部测试包可以提供证据，但不能仅凭同包测试能够调用就声称外部测试方
可用。固定名称是对外合同，不限制内部结构；下文中的“目标节点 ID 类型”、
“目标消息类型”等是类型槽，Agent 必须换成真实、导出的 Go 类型，不能原样
生成占位名称。

## 1. 消息捕获

统一公开：

```go
type MessageHandle struct { id uint64 }
type MessageKind string

type PendingMessage struct {
    Handle  MessageHandle
    Source  /* 目标节点 ID 类型 */
    Target  /* 目标节点 ID 类型 */
    Kind    MessageKind
    Message /* 目标消息载体 */
}

type MessageController

func NewMessageController(/* 目标依赖 */) *MessageController
func (c *MessageController) Pending() []PendingMessage
func (c *MessageController) Drop(handle MessageHandle) error
func (c *MessageController) Clear()
```

消息载体优先使用统一原生结构，其次使用已有公共接口；两者都不存在时生成
带明确变体的类型化包装。不能用裸 `any`、只暴露序列化字节或增加
`Metadata any` 来回避类型设计。目标可以增加 `ChannelID` 等有明确含义的
类型化字段。

配置 Controller 后，边界内所有逻辑跨节点协议请求、响应和单向消息都必须
在投递前进入缓存，且不能与原协议消费者竞争。广播按接收节点拆成多个缓存
实例；同步请求—响应要包装原完成机制，使请求和响应分别缓存，响应交换
Source/Target 并获得新 Handle。节点内部定时事件、本地存储/WAL 工作、客户
端负载和边界外网络不进入该缓存。

Handle 是不透明稳定引用，不是切片下标、节点 ID 或协议消息 ID。消息离开
缓存后 Handle 失效，不能重新指向其他消息。缓存操作线程安全、保持接收
顺序，不得静默覆盖或驱逐。

必须有两层复制隔离：生产者到 Controller 的独立副本，以及每次 `Pending`
返回的新深拷贝快照。`Inject` 始终使用 Controller 私有副本。嵌套 slice、
map、指针、接口和流都要处理；流可以使用内存、临时文件或目标存储，但要
独立可重放并在消息离开时释放。

v0.1 不提供 `Take`，也不支持修改、重定向、复制或凭空构造消息。测试方先
用 `Pending` 按消息内容、来源、目标或状态选择，再用 Handle 执行动作。

## 2. 消息注入

统一公开：

```go
func (c *MessageController) Inject(handle MessageHandle) error

var ErrMessageNotPending error
var ErrTargetUnavailable error
var ErrMessageNotAccepted error
```

错误必须能用 `errors.Is` 分类。`Inject` 根据捕获时保存的真实目标绑定，将
Controller 私有消息副本交给该方向的正常协议输入入口。完成点是输入边界
确认接受，不等待出队、状态转换、响应、提交或系统静止。

| 情况 | 缓存结果 |
| --- | --- |
| Handle 无效、目标不可用、入口明确拒绝 | 返回错误，消息保留 |
| 输入入口确认接受 | 返回成功，消息移除，Handle 失效 |
| 接受后协议处理失败 | Inject 仍成功，消息不恢复 |

异步入口进入队列或 channel 即可视为接受。如果目标无法区分“未接受”和
“超时但可能已接受”，报告必须写明限制，不能自行恢复造成重复投递。注入
请求必须进入请求入口，不能用构造响应代替；注入产生的跨节点响应仍重新
进入缓存。

## 3. 时间控制

统一公开 `TimeController`、`NewTimeController(...)` 和：

```go
Advance(steps uint64) error
```

测试模式下，不调用 `Advance`，协议时间就不前进；消息操作、观察和外部
输入不能附带推进。一个 step 统一推进所有 Running 节点一个目标定义的时间
单位，`Advance(n)` 等价于连续 n 次 `Advance(1)`，不能跳过中间 timer。

内部可以逐节点调用原生 Tick，也可以推进共享虚拟时钟；到期事件必须通过
原 timeout 路径提交，不能直接制造选举等结果。返回只保证时间和到期事件
已经提交，不保证协议处理或提交完成。v0.1 不提供单节点漂移。

## 4. 随机性控制

统一公开 `RandomController`、`RandomChoice`、
`NewRandomController(seed int64, ...)` 和 `Choices() []RandomChoice`。
每个受控节点或组件拥有自己的 Controller。

同一 seed 与同一随机调用顺序必须重现同一选择序列，但每次决策仍取下一个
值，不能把随机值固定成常量。`Choices` 返回按顺序记录的最终语义值深拷贝，
例如目标实际采用的 duration 或 index，而不是原始随机比特。

只控制会影响协议状态或测试时机、且无法从其他受控接口完整得知的隐藏非
密码学随机选择。密码学随机、外围 ID、测试数据和边界外随机不在范围内；
没有此类选择时报告 `NOT_APPLICABLE`。v0.1 不要求直接指定单次结果或脚本化
轨迹回放。

## 5. 生命周期控制

统一公开：

```go
type LifecycleController

func NewLifecycleController(/* 目标依赖 */) *LifecycleController
func (c *LifecycleController) Pause(node /* 目标节点 ID */) error
func (c *LifecycleController) Resume(node /* 目标节点 ID */) error
func (c *LifecycleController) Stop(node /* 目标节点 ID */) error
func (c *LifecycleController) Crash(node /* 目标节点 ID */) error
func (c *LifecycleController) Restart(node /* 目标节点 ID */) error
```

- Pause/Resume：保留同一个运行实例和易失状态；暂停期间不处理消息、不推进
  节点时间、不产生输出。只隔离网络不算 Pause。
- Stop：执行正常关闭，允许目标完成正常清理和持久化；之后可以按目标的
  post-stop 状态 Restart。
- Crash：不额外刷新协议状态，丢弃运行实例和易失状态，只保留目标此前已
  持久化的状态。Pause、正常 Stop 或保存整份内存不能冒充 Crash。
- Restart：记录先前是 Stop 还是 Crash，使用相同身份、配置和目标正常恢复
  入口；Crash 后必须创建新运行实例。协议追赶由测试方用其他接口驱动。

已进入 MessageController 的消息在节点不可用期间继续保留；节点不可用时
Inject 失败且不移除消息。节点内部未处理队列在 Crash 时作为易失状态丢失；
Paused、Stopped、Crashed 节点不接收时间步骤。

Agent 尝试五项操作，并逐项标注：

- `facade_only`：只包装已有公开行为；
- `core_hook`：需要默认关闭、保持语义的窄核心接缝，可以实现；
- `core_semantics_required`：会改变协议、持久化、状态转换或顺序，不实现，
  对应方法返回可由 `errors.Is` 判断的 `ErrLifecycleUnsupported`。

## 6. 状态观察

优先复用目标已有的安全类型化 Status、State 或 getter，不统一命名、不设计
通用状态 Schema。对每个入口列出范围、类型、可见内容、快照安全、一致性、
完成语义和示例。只有缺少安全公开入口时，才增加
`Observe() /* 目标状态类型 */`。

观察必须线程安全、无副作用、不推进时间，并返回无可变别名的深快照。
v0.1 只保证单节点快照，不承诺同时冻结所有节点；多个 getter 拼接的时间
一致性限制必须说明。

## 7. 外部输入

这项能力只发现和列出已有普通应用工作入口，不生成统一 Controller，也不把
目标 API 改名为 Submit。包括命令、复制日志、交易、普通读取和成员变更
请求；排除协议消息、时间、生命周期、状态观察、应用已提交结果、bootstrap、
restore、诊断和管理操作。

每个入口记录类别、公开符号、具体输入类型、前置条件、接受/处理/提交等完成
语义、结果取得方式、最小示例和推荐进程内路径。只有内部入口时如实报告，
不为满足清单而发明业务 API。

## 实现与报告

固定的是测试方看到的功能合同，而非目标内部结构。Agent 2 可以采用包装、
hook、依赖注入、配置或 accessor，但必须给出完整构造和接线示例。它只增加
验证新增行为所需的最少测试，不生成场景语言、调度策略、故障模型、断言或
正确性 oracle。

`capability-report.json` 记录修改前事实，`interface-report.json` 记录生成
接口和范围，中文 `USAGE.md` 给出接口矩阵、构造方式和示例，`AUDIT.md`
记录独立审查。`patch` 能独立生成候选，`repair` 只是可选质量增强。
