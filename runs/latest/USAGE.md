# etcd-raft 测试接口清单

本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。
详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。

## 快速接口矩阵

| 能力 | 修改前状态 | 目标已有入口 | 本次生成入口 | 当前结论 |
|---|---|---|---|---|
| 消息捕获 | `PATCHABLE` | `rafttest.InteractionEnv.Messages`<br>`rafttest.ProcessReady`<br>`rafttest.DeliverMsgs`<br>等 7 项 | — | 尚需低侵入补充 |
| 消息注入 | `PATCHABLE` | `rafttest.DeliverMsgs`<br>`rafttest.SendSnapshot`<br>`rafttest.InteractionEnv.Nodes`<br>等 5 项 | — | 尚需低侵入补充 |
| 时间控制 | `SUPPORTED` | `Node.Tick`<br>`RawNode.Tick`<br>`RawNode.TickQuiesced`<br>等 5 项 | — | 直接复用目标已有接口 |
| 随机性控制 | `PATCHABLE` | `raft.SetRandomizedElectionTimeout (test-only export, raft package test builds only)`<br>`rafttest.InteractionOpts.SetRandomizedElectionTimeout`<br>`rafttest.Handle (set-randomized-election-timeout command)` | — | 尚需低侵入补充 |
| 生命周期控制 | `SUPPORTED` | `Node.Stop`<br>`StartNode`<br>`RestartNode`<br>等 7 项 | — | 直接复用目标已有接口 |
| 状态观察 | `SUPPORTED` | `Node.Status`<br>`RawNode.Status`<br>`RawNode.BasicStatus`<br>等 9 项 | — | 直接复用目标已有接口 |
| 外部输入 | `SUPPORTED` | `Node.Propose`<br>`Node.ProposeConfChange`<br>`Node.ReadIndex`<br>等 10 项 | — | 直接复用目标已有接口 |

## 接口详情与示例

### 消息捕获

**目标已有入口**

- `rafttest.InteractionEnv.Messages`
- `rafttest.ProcessReady`
- `rafttest.DeliverMsgs`
- `rafttest.Stabilize`
- `rafttest.SendSnapshot`
- `Node.Ready`
- `RawNode.Ready`

**调用示例**

```go
// Requires: env *rafttest.InteractionEnv
_ = env.ProcessReady(0)
msgs := env.Messages
env.Messages = nil // clear the cache
_ = msgs
```

### 消息注入

**目标已有入口**

- `rafttest.DeliverMsgs`
- `rafttest.SendSnapshot`
- `rafttest.InteractionEnv.Nodes`
- `RawNode.Step`
- `Node.Step`

**调用示例**

```go
// Requires: env *rafttest.InteractionEnv
n := env.DeliverMsgs(-1, rafttest.Recipient{ID: 2})
_ = n
```

### 时间控制

**目标已有入口**

- `Node.Tick`
- `RawNode.Tick`
- `RawNode.TickQuiesced`
- `rafttest.Tick`
- `rafttest.Handle (tick-election / tick-heartbeat)`

**调用示例**

```go
// Requires: rn *raft.RawNode
rn.Tick()
```

```go
// Requires: env *rafttest.InteractionEnv
_ = env.Tick(0, env.Nodes[0].Config.ElectionTick)
```

### 随机性控制

**目标已有入口**

- `raft.SetRandomizedElectionTimeout (test-only export, raft package test builds only)`
- `rafttest.InteractionOpts.SetRandomizedElectionTimeout`
- `rafttest.Handle (set-randomized-election-timeout command)`

### 生命周期控制

**目标已有入口**

- `Node.Stop`
- `StartNode`
- `RestartNode`
- `RawNode.Tick`
- `RawNode.Step`
- `RawNode.Ready`
- `RawNode.Advance`

**调用示例**

```go
// Requires: n raft.Node, st *raft.MemoryStorage
n.Stop()
rn := raft.RestartNode(&raft.Config{ID: 1, ElectionTick: 10, HeartbeatTick: 1, Storage: st, MaxSizePerMsg: 1024 * 1024, MaxInflightMsgs: 256})
_ = rn
```

### 状态观察

**目标已有入口**

- `Node.Status`
- `RawNode.Status`
- `RawNode.BasicStatus`
- `RawNode.WithProgress`
- `rafttest.Status`
- `rafttest.RaftLog`
- `MemoryStorage.FirstIndex`
- `MemoryStorage.LastIndex`
- `MemoryStorage.Entries`

**调用示例**

```go
// Requires: rn *raft.RawNode
st := rn.Status()
fmt.Println(st.RaftState, st.Term, st.Commit, st.Applied)
```

### 外部输入

**目标已有入口**

- `Node.Propose`
- `Node.ProposeConfChange`
- `Node.ReadIndex`
- `Node.ApplyConfChange`
- `RawNode.Propose`
- `RawNode.ProposeConfChange`
- `RawNode.ReadIndex`
- `RawNode.ApplyConfChange`
- `rafttest.InteractionEnv.Propose`
- `rafttest.InteractionEnv.ProposeConfChange`

**调用示例**

```go
// Requires: rn *raft.RawNode
err := rn.Propose([]byte("cmd"))
_ = err
```

```go
// Requires: rn *raft.RawNode
cc := raftpb.ConfChangeV2{Changes: []raftpb.ConfChangeSingle{{Type: raftpb.ConfChangeAddNode, NodeID: 2}}}
_ = rn.ProposeConfChange(cc)
```
