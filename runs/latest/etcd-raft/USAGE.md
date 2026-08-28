# etcd-raft 测试接口清单

> [!WARNING]
> 本次运行未完成，以下内容仅反映中断前已经产生的阶段性结果。
> 生成接口、调用示例和 Reviewer 结论可能缺失，不得作为最终使用说明。

本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。
详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。

## 快速接口矩阵

| 能力 | 修改前状态 | 目标已有入口 | 本次生成入口 | 当前结论 |
|---|---|---|---|---|
| 消息捕获 | `PATCHABLE` | `raft.RawNode.Ready`<br>`raft.RawNode.Advance`<br>`raft.Node.Ready`<br>等 9 项 | `MessageCache`<br>`MessageCache.Add`<br>`MessageCache.Len`<br>等 22 项 | 已生成接口；覆盖 3 条路径 |
| 消息注入 | `PATCHABLE` | `raft.RawNode.Step`<br>`raft.Node.Step`<br>`rafttest.InteractionEnv.DeliverMsgs`<br>等 4 项 | `InteractionEnv.DeliverMsg`<br>`InteractionEnv.Step`<br>`InteractionEnv.TakeMsg`<br>等 6 项 | 已生成接口；覆盖 3 条路径 |
| 时间控制 | `PATCHABLE` | `raft.RawNode.Tick`<br>`raft.RawNode.TickQuiesced`<br>`raft.Node.Tick`<br>等 4 项 | `Node.Tick` | 已生成接口；覆盖 3 条路径 |
| 随机性控制 | `PATCHABLE` | `rafttest.InteractionOpts.SetRandomizedElectionTimeout` | `Config.ElectionTimeoutRand`<br>`RawNode.SetRandomizedElectionTimeout` | 已生成接口；覆盖 3 条路径 |
| 生命周期控制 | `SUPPORTED` | `raft.NewRawNode`<br>`raft.RestartNode`<br>`raft.StartNode`<br>等 9 项 | — | 直接复用目标已有接口 |
| 状态观察 | `SUPPORTED` | `raft.RawNode.Status`<br>`raft.RawNode.BasicStatus`<br>`raft.RawNode.WithProgress`<br>等 9 项 | — | 直接复用目标已有接口 |
| 外部输入 | `SUPPORTED` | `raft.RawNode.Propose`<br>`raft.RawNode.ProposeConfChange`<br>`raft.RawNode.ReadIndex`<br>等 8 项 | — | 直接复用目标已有接口 |

## 消息控制调用顺序

1. 按报告所列方式启用目标原生的消息控制面。
2. 调用缓存枚举入口，获得可检查的消息内容和与之绑定的实例引用。
3. 测试代码根据目标原生消息字段选择实例；ConsensusSeam 不决定选择策略。
4. 将枚举返回的同一实例引用交给取出、丢弃或注入入口，不要重新猜测切片位置。
5. 根据下方记录的缓存变化与失败语义决定是否重试或保留消息。

## 接口详情与示例

### 消息捕获

**目标已有入口**

- `raft.RawNode.Ready`
- `raft.RawNode.Advance`
- `raft.Node.Ready`
- `raft.Node.Advance`
- `rafttest.InteractionEnv.ProcessReady`
- `rafttest.InteractionEnv.Messages`
- `rafttest.InteractionEnv.DeliverMsgs`
- `rafttest.InteractionEnv.ProcessAppendThread`
- `rafttest.InteractionEnv.ProcessApplyThread`

**本次生成入口**

- `MessageCache`
- `MessageCache.Add`
- `MessageCache.Len`
- `MessageCache.Messages`
- `MessageCache.TakeMsg`
- `MessageCache.DropMsg`
- `MessageCache.DropMsgs`
- `MessageCache.Clear`
- `Driver`
- `NewDriver`
- `Driver.Ready`
- `Driver.Advance`
- `Driver.Len`
- `Driver.Messages`
- `Driver.TakeMsg`
- `Driver.DropMsg`
- `Driver.DropMsgs`
- `Driver.ClearMessages`
- `InteractionEnv.TakeMsg`
- `InteractionEnv.DropMsg`
- `InteractionEnv.DropMsgs`
- `InteractionEnv.ClearMessages`

**启用与使用范围**

New exported rafttest APIs (MessageCache, Driver, InteractionEnv cache operations) exercised by new focused tests in rafttest/message_cache_test.go (TestMessageCache, TestDriverCaptureAndDeliver, TestInteractionEnvCacheOps). No existing test files were modified.

**缓存实例引用**

A cached instance is the target-native raftpb.Message value retained in cache order; TakeMsg/DropMsg/DeliverMsg select by predicate and return or remove the exact retained instance with its routing fields (From, To, Type). Once removed, a later Take cannot return it; selection always runs over the current cache contents, so a stale reference is rejected by absence and never silently retargets another message. No permanent numeric message IDs are introduced; identity is the retained instance itself, stable for as long as it stays in the cache.

**目标绑定方式**

Capture returns routing information with each taken instance. Binding to a real target happens at injection: on the rafttest env path the destination is resolved from the message's To against env.Nodes (the env-owned registry); on the RawNode path the test owns the node mapping and either passes it to Driver.Deliver as a bind function (which maps and validates To) or calls the target's Step directly after TakeMsg. Identifier arithmetic is not used as binding; the env registry or the test's own map validates the relationship.

**缓存变化与失败语义**

Enumerate (Messages/Len): returns an ordered deep-copied snapshot; the cache is unchanged. TakeMsg: removes and returns the selected instance; the cache shrinks by one. DropMsg/DropMsgs: remove the selected instance(s) without delivering. Clear/ClearMessages: remove all instances. Delivery (DeliverMsg/Driver.Deliver): the entry is removed before Step runs; a synchronous Step error is returned without restoring the entry; no match (ErrNoMessage) or unknown target leaves the cache unchanged. Unconfirmed asynchronous delivery does not exist in this library: Step is synchronous and its effects surface in the target's next Ready, which re-enters the same cache (env.Messages via ProcessReady, or the driver/MessageCache via Ready capture).

**调用示例**

```go
// Requires: rn *raft.RawNode, st *raft.MemoryStorage, peers map[uint64]*raft.RawNode
if rn.HasReady() {
    rd := rn.Ready()
    st.Append(rd.Entries)
    for _, m := range rd.Messages {
        peers[m.To].Step(m)
    }
    rn.Advance(rd)
}
```

```go
// Requires: env *rafttest.InteractionEnv
if err := env.ProcessReady(0); err != nil {
    panic(err)
}
env.DeliverMsgs(-1, rafttest.Recipient{ID: 2})
```

```go
// Requires: rn *raft.RawNode, st *raft.MemoryStorage
d := rafttest.NewDriver(rn)
for d.HasReady() {
    rd, hasWork := d.Ready()
    if hasWork {
        _ = st.Append(rd.Entries)
    }
    d.Advance(rd)
}
m, ok := d.TakeMsg(func(m raftpb.Message) bool { return m.Type == raftpb.MsgApp })
if ok {
    _ = m.To
}
```

```go
// Requires: env *rafttest.InteractionEnv
_ = env.ProcessReady(0)
m, ok := env.TakeMsg(func(m raftpb.Message) bool { return m.Type == raftpb.MsgApp })
if ok {
    _ = m.To
}
```

```go
// Requires: n raft.Node
cache := rafttest.NewMessageCache()
rd := <-n.Ready()
cache.Add(rd.Messages...)
n.Advance()
m, ok := cache.TakeMsg(func(m raftpb.Message) bool { return m.Type == raftpb.MsgHeartbeat })
_ = m
_ = ok
```

### 消息注入

**目标已有入口**

- `raft.RawNode.Step`
- `raft.Node.Step`
- `rafttest.InteractionEnv.DeliverMsgs`
- `rafttest.InteractionEnv.Stabilize`

**本次生成入口**

- `InteractionEnv.DeliverMsg`
- `InteractionEnv.Step`
- `InteractionEnv.TakeMsg`
- `Driver.Deliver`
- `Driver.TakeMsg`
- `MessageCache.TakeMsg`

**启用与使用范围**

Injection forms exercised by new focused tests in rafttest/message_cache_test.go: combined DeliverMsg round trip (heartbeat request and response through the env cache), combined Driver.Deliver vote/append round trips on the two-node RawNode group, and separated TakeMsg + target.Step delivery with commit advancement. No existing test files were modified.

**缓存实例引用**

The selected cached instance is the target-native raftpb.Message value retained in cache order; DeliverMsg/Driver.Deliver/TakeMsg select it by predicate and the returned message is the exact captured instance with its routing fields. The entry is removed on take/deliver, so a later operation cannot return or deliver a removed instance (stale references are rejected by absence, never silently retargeted). No permanent numeric message IDs are introduced.

**目标绑定方式**

Env path: the destination is resolved from the cached message's To field against env.Nodes (the env-owned registry, the same mapping used by the existing DeliverMsgs); an out-of-range To is rejected before removal and the cache is left unchanged. RawNode direct path: the test owns the node mapping; the combined Driver.Deliver takes a test-supplied bind func(msg) *raft.RawNode that maps and validates To (nil target returns an explicit error and leaves the cache unchanged); the separated form calls the target's Step directly after TakeMsg. Identifier arithmetic is not used as binding; the env registry or the test's own map validates the relationship.

**缓存变化与失败语义**

DeliverMsg/Driver.Deliver (combined): no match -> cache unchanged and ErrNoMessage returned; unknown or unavailable target -> cache unchanged and an explicit error returned; otherwise the entry is removed before Step runs and a synchronous Step error is returned without restoring the entry. Step/TakeMsg (separated): TakeMsg removes the entry and returns it with routing; Step does not touch the cache. Unconfirmed asynchronous delivery does not exist (Step is synchronous); request/response completion is preserved because responses re-enter the same cache through the target's next Ready (ProcessReady on the env path, Ready capture on the driver/MessageCache paths) and are delivered through the same operations. Retry, requeue, duplication, loss, and ordering are tester policy.

**调用示例**

```go
// Requires: env *rafttest.InteractionEnv
env.DeliverMsgs(-1, rafttest.Recipient{ID: 2, Drop: true})
```

```go
// Requires: rn *raft.RawNode
_ = rn.Step(raftpb.Message{Type: raftpb.MsgHeartbeat, From: 2, To: 1, Term: 3})
```

```go
// Requires: env *rafttest.InteractionEnv
if err := env.DeliverMsg(func(m raftpb.Message) bool { return m.Type == raftpb.MsgHeartbeat }); err != nil {
    panic(err)
}
```

```go
// Requires: env *rafttest.InteractionEnv
m, ok := env.TakeMsg(func(m raftpb.Message) bool { return m.Type == raftpb.MsgApp })
if ok {
    _ = env.Step(m)
}
```

```go
// Requires: d *rafttest.Driver, peers map[uint64]*raft.RawNode
if err := d.Deliver(func(m raftpb.Message) bool { return m.Type == raftpb.MsgApp }, func(m raftpb.Message) *raft.RawNode {
    return peers[m.To]
}); err != nil {
    panic(err)
}
```

```go
// Requires: d *rafttest.Driver, peers map[uint64]*raft.RawNode
m, ok := d.TakeMsg(func(m raftpb.Message) bool { return m.Type == raftpb.MsgHeartbeat })
if ok {
    _ = peers[m.To].Step(m)
}
```

### 时间控制

**目标已有入口**

- `raft.RawNode.Tick`
- `raft.RawNode.TickQuiesced`
- `raft.Node.Tick`
- `rafttest.InteractionEnv.Tick`

**本次生成入口**

- `Node.Tick`

**启用与使用范围**

Same code path with no test-only branch: after Tick returns, the advance has been accepted by the run loop and is applied before any later request or observation serviced through the same loop. RawNode.Tick (rawnode.go:64) and rafttest InteractionEnv.Tick (interaction_env_handler_tick.go:34) remain exact synchronous single-tick advances and are unchanged.

**调用示例**

```go
// Requires: rn *raft.RawNode
rn.Tick()
```

```go
// Requires: env *rafttest.InteractionEnv
_ = env.Tick(0, 3)
```

```go
// Requires: n raft.Node
n.Tick() // blocks until the tick is accepted; never silently dropped
```

```go
// Requires: n raft.Node
for i := 0; i < 10; i++ {
	n.Tick() // all 10 advances are guaranteed to be applied
}
```

### 随机性控制

**目标已有入口**

- `rafttest.InteractionOpts.SetRandomizedElectionTimeout`

**本次生成入口**

- `Config.ElectionTimeoutRand`
- `RawNode.SetRandomizedElectionTimeout`

**启用与使用范围**

With Config.ElectionTimeoutRand set (or the RawNode setter applied), the test supplies and therefore knows every draw; a constant or counter-based function reproduces the same sequence under the same initial state and tick schedule, and the node starts its election at the exact tick implied by the supplied value.

**缓存实例引用**

Per-node scope: Config.ElectionTimeoutRand is copied into the raft runtime at construction (newRaft) and consulted on every draw of that instance; RawNode.SetRandomizedElectionTimeout targets exactly the RawNode instance it is called on. A shared deterministic function across nodes is safe because assignment is per-instance and the function is stateless with respect to instance identity.

**调用示例**

```go
// Requires: st *raft.MemoryStorage
cfg := &raft.Config{ID: 1, ElectionTick: 10, HeartbeatTick: 1, Storage: st, MaxInflightMsgs: 256}
cfg.ElectionTimeoutRand = func(electionTick int) int { return electionTick + 2 }
rn, err := raft.NewRawNode(cfg)
if err != nil {
    panic(err)
}
_ = rn
```

```go
// Requires: rn *raft.RawNode
rn.SetRandomizedElectionTimeout(12)
```

```go
env := rafttest.NewInteractionEnv(&rafttest.InteractionOpts{
    SetRandomizedElectionTimeout: (*raft.RawNode).SetRandomizedElectionTimeout,
})
_ = env
```

### 生命周期控制

**目标已有入口**

- `raft.NewRawNode`
- `raft.RestartNode`
- `raft.StartNode`
- `raft.Node.Stop`
- `raft.MemoryStorage`
- `rafttest.Node.RawNode`
- `rafttest.Node.Storage`
- `rafttest.Node.Config`
- `rafttest.InteractionEnv.AddNodes`

**调用示例**

```go
// Requires: st *raft.MemoryStorage, cfg *raft.Config
cfg.Storage = st
rn, err := raft.NewRawNode(cfg)
if err != nil {
    panic(err)
}
_ = rn
```

```go
// Requires: c *raft.Config
n := raft.RestartNode(c)
_ = n
```

### 状态观察

**目标已有入口**

- `raft.RawNode.Status`
- `raft.RawNode.BasicStatus`
- `raft.RawNode.WithProgress`
- `raft.Node.Status`
- `rafttest.InteractionEnv.Status`
- `rafttest.InteractionEnv.RaftLog`
- `raft.MemoryStorage.Entries`
- `raft.MemoryStorage.FirstIndex`
- `raft.MemoryStorage.LastIndex`

**调用示例**

```go
// Requires: rn *raft.RawNode
st := rn.Status()
fmt.Println(st.RaftState, st.Term, st.Commit, st.Applied)
```

```go
// Requires: rn *raft.RawNode
bs := rn.BasicStatus()
_ = bs.Lead
```

### 外部输入

**目标已有入口**

- `raft.RawNode.Propose`
- `raft.RawNode.ProposeConfChange`
- `raft.RawNode.ReadIndex`
- `raft.Node.Propose`
- `raft.Node.ProposeConfChange`
- `raft.Node.ReadIndex`
- `rafttest.InteractionEnv.Propose`
- `rafttest.InteractionEnv.ProposeConfChange`

**调用示例**

```go
// Requires: rn *raft.RawNode
_ = rn.Propose([]byte("write-a"))
```

```go
// Requires: n raft.Node, ctx context.Context
_ = n.ProposeConfChange(ctx, raftpb.ConfChangeV2{Changes: []raftpb.ConfChangeSingle{{Type: raftpb.ConfChangeAddNode, NodeID: 4}}})
```

```go
// Requires: env *rafttest.InteractionEnv
_ = env.Propose(0, []byte("x"))
```
