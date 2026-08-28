# etcd-raft 测试接口清单

> [!WARNING]
> 本次运行未完成，以下内容仅反映中断前已经产生的阶段性结果。
> 生成接口、调用示例和 Reviewer 结论可能缺失，不得作为最终使用说明。

本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。
详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。

## 快速接口矩阵

| 能力         | 修改前状态    | 目标已有入口                                                                                                                                                                                                                                                                                                    | 本次生成入口                                                                                                              | 当前结论                               |
| ------------ | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| 消息捕获     | `PATCHABLE` | `RawNode.Ready() / readyWithoutAccept() (one-shot batch)Node.Ready() <-chan Ready (channel handoff)``rafttest InteractionEnv.ProcessReady(idx) (captures into env.Messages)`等 6 项                                                                                                                         | `InteractionEnv.EnumerateMessagesInteractionEnv.TakeMessage``InteractionEnv.DropMessage`等 6 项                       | 已生成接口；覆盖 3 条路径，未覆盖 3 条 |
| 消息注入     | `PATCHABLE` | `rafttest InteractionEnv.DeliverMsgs(typ, recipients...) (Take+Inject combined)rafttest InteractionEnv.SendSnapshot(fromIdx, toIdx) (inject synthesized MsgSnap into cache)``RawNode.Step(m pb.Message) (raw ingress primitive)`等 4 项                                                                     | `InteractionEnv.InjectMessageInteractionEnv.DeliverMsgs``InteractionEnv.SendSnapshot`                                 | 已生成接口；覆盖 3 条路径，未覆盖 2 条 |
| 时间控制     | `SUPPORTED` | `RawNode.Tick()RawNode.TickQuiesced()``Node.Tick()`等 5 项                                                                                                                                                                                                                                                  | —                                                                                                                        | 直接复用目标已有接口                   |
| 随机性控制   | `PATCHABLE` | `raft.setRandomizedElectionTimeout(r, v) (package-internal)raft.SetRandomizedElectionTimeout(rn, v) (exported from raft_test.go; test-binary-only)``rafttest set-randomized-election-timeout command (via InteractionOpts.SetRandomizedElectionTimeout, plumbed only by this module's interaction_test.go)` | `Config.RandomizedElectionTimeoutInteractionOpts.OnConfig`                                                              | 已生成接口；覆盖 4 条路径，未覆盖 1 条 |
| 生命周期控制 | `PATCHABLE` | `Node.Stop()Node.StartNode(c, peers)``Node.RestartNode(c)`等 6 项                                                                                                                                                                                                                                           | `InteractionEnv.StopNodeInteractionEnv.RestartNode``InteractionEnv.Handle (stop-node / restart-node commands)`等 4 项 | 已生成接口；覆盖 5 条路径，未覆盖 1 条 |
| 状态观察     | `SUPPORTED` | `RawNode.Status()RawNode.BasicStatus()``RawNode.WithProgress(visitor)`等 6 项                                                                                                                                                                                                                               | —                                                                                                                        | 直接复用目标已有接口                   |
| 外部输入     | `SUPPORTED` | `Node.Propose(ctx, data)Node.ProposeConfChange(ctx, cc)``Node.ReadIndex(ctx, rctx)`等 8 项                                                                                                                                                                                                                  | —                                                                                                                        | 直接复用目标已有接口                   |

## 消息控制调用顺序

1. 按报告所列方式启用目标原生的消息控制面。
2. 调用缓存枚举入口，获得可检查的消息内容和与之绑定的实例引用。
3. 测试代码根据目标原生消息字段选择实例；ConsensusSeam 不决定选择策略。
4. 将枚举返回的同一实例引用交给取出、丢弃或注入入口，不要重新猜测切片位置。
5. 根据下方记录的缓存变化与失败语义决定是否重试或保留消息。

## 接口详情与示例

### 消息捕获

**目标已有入口**

- `RawNode.Ready() / readyWithoutAccept() (one-shot batch)`
- `Node.Ready() <-chan Ready (channel handoff)`
- `rafttest InteractionEnv.ProcessReady(idx) (captures into env.Messages)`
- `rafttest InteractionEnv.DeliverMsgs(typ, recipients...) (consume/drop from env.Messages)`
- `rafttest InteractionEnv.Messages (public enumeration)`
- `rafttest ProcessAppendThread/ProcessApplyThread (consume AppendWork/ApplyWork FIFO)`

**本次生成入口**

- `InteractionEnv.EnumerateMessages`
- `InteractionEnv.TakeMessage`
- `InteractionEnv.DropMessage`
- `InteractionEnv.ClearMessages`
- `InteractionEnv.ProcessReady`
- `InteractionEnv.DeliverMsgs`

**启用与使用范围**

Public rafttest InteractionEnv facade (NewInteractionEnv + AddNodes + ProcessReady activation); the new per-instance operations are regular public methods, usable by any external consumer that imports go.etcd.io/raft/v3/rafttest.

**缓存实例引用**

MessageHandle is an opaque struct with unexported fields (env pointer plus a monotonically increasing per-env id assigned at append time). It is obtained only from EnumerateMessages, cannot be forged by tests, and continues to denote the same concrete cache instance (including among equal-valued duplicates) until that instance is consumed by TakeMessage/InjectMessage, removed by DropMessage/ClearMessages, or delivered/dropped by DeliverMsgs. Scope: the pending store of one InteractionEnv instance.

**缓存变化与失败语义**

EnumerateMessages: read-only, cache unchanged, returns deep copies plus handles. TakeMessage: removes exactly the referenced instance from env.Messages (and its id); returns a deep copy; stale handle returns ok=false and mutates nothing. DropMessage: removes exactly the referenced instance without delivery; stale handle returns false. ClearMessages: removes all instances and returns the count; all handles become invalid. DeliverMsgs: bulk removal per recipient/type (existing semantics), handles of handled messages become invalid. Successful injection: see message_injection.cache_effects.

**仍未覆盖**

- RawNode.Ready / readyWithoutAccept one-shot batch path: Ready hands out r.msgs as a single batch and Advance clears it; there is no retained test cache, and adding one would change the Ready output/Advance contract on the production path (INVASIVE).
- Node.Ready channel path: one-shot channel handoff with no retained cache; same invasive constraint as RawNode.Ready.
- Internal network harness (rafttest/node.go + network.go): unexported in-package transport simulation with per-recipient channel queues and no per-instance operations; it simulates the real network send, which is outside the declared capture boundary.

**调用示例**

```go
env.ProcessReady(0)
```

```go
for _, m := range env.Messages { _ = m.Type; _ = m.To }
```

```go
n := env.DeliverMsgs(-1, rafttest.Recipient{ID: 2})
```

```go
env := rafttest.NewInteractionEnv(nil)
cfg := raftConfigStub() // ElectionTick=3, HeartbeatTick=1
env.AddNodes(3, cfg, raftpb.Snapshot{Metadata: raftpb.SnapshotMetadata{ConfState: raftpb.ConfState{Voters: []uint64{1, 2, 3}}, Index: 2}})
env.Campaign(0)
env.ProcessReady(0) // capture: MsgVote messages enter the cache
for _, em := range env.EnumerateMessages() {
    if em.Msg.Type == raftpb.MsgVote && em.Msg.To == 2 {
        env.InjectMessage(em.Handle) // take from cache, Step into node 2
    } else {
        env.DropMessage(em.Handle)
    }
}
msgs := env.EnumerateMessages()
require.Len(t, msgs, 1) // only the response captured later
env.ClearMessages()
```

### 消息注入

**目标已有入口**

- `rafttest InteractionEnv.DeliverMsgs(typ, recipients...) (Take+Inject combined)`
- `rafttest InteractionEnv.SendSnapshot(fromIdx, toIdx) (inject synthesized MsgSnap into cache)`
- `RawNode.Step(m pb.Message) (raw ingress primitive)`
- `Node.Step(ctx, m pb.Message) (raw ingress primitive, async delivery)`

**本次生成入口**

- `InteractionEnv.InjectMessage`
- `InteractionEnv.DeliverMsgs`
- `InteractionEnv.SendSnapshot`

**启用与使用范围**

Public rafttest InteractionEnv facade; InjectMessage is a regular public method callable by any external consumer importing go.etcd.io/raft/v3/rafttest.

**缓存实例引用**

Same MessageHandle as message capture: opaque, per-env unique id, stable until the instance is consumed, removed, or cleared; duplicates remain separately addressable.

**目标绑定方式**

The cached destination is resolved to the real target object using the env's existing node collection: toIdx = int(msg.To - 1), validated against len(env.Nodes) before the message is removed; delivery then calls env.Nodes[toIdx].Step(msg) on the actual RawNode. No caller-supplied target object is needed, and no target ID alone is used as binding.

**缓存变化与失败语义**

Success: the referenced instance is removed from env.Messages and delivered via RawNode.Step; the handle becomes invalid. Synchronous Step error: the instance is already removed from the cache and the error is returned; retry/requeue/loss policy is the test's (documented). Unknown destination (msg.To out of range): error returned, message remains cached. Stale/foreign handle: error returned, nothing removed. DeliverMsgs: bulk removal with delivery or drop; handled handles invalidated. EnumerateMessages/TakeMessage: see message_capture.cache_effects. Unconfirmed asynchronous delivery: not applicable on this path (RawNode.Step is synchronous); the async Node.Step path is uncovered.

**仍未覆盖**

- RawNode.Step and Node.Step raw ingress primitives: they are protocol input primitives on paths without a capture cache; a cache-linked injection facade there would require adding a retained capture cache to RawNode/Node, which changes the Ready output contract (INVASIVE).
- Node.Step asynchronous path: delivery is channel-accept only and protocol processing is asynchronous; without a capture cache no combined wrapper could report confirmed delivery, so this path is reported rather than force-covered.

**调用示例**

```go
env.DeliverMsgs(raftpb.MsgApp, rafttest.Recipient{ID: 2})
```

```go
env.SendSnapshot(0, 1)
```

```go
err := rn.Step(pb.Message{Type: pb.MsgVote, From: 2, To: 1, Term: 3})
```

```go
env := rafttest.NewInteractionEnv(nil)
env.AddNodes(3, cfg, snap)
env.Campaign(0)
env.ProcessReady(0) // capture MsgVote messages
for _, em := range env.EnumerateMessages() {
    if em.Msg.To == 2 {
        if err := env.InjectMessage(em.Handle); err != nil {
            t.Fatal(err) // synchronous RawNode.Step error; message already taken
        }
    }
}
env.ProcessReady(1) // node 2's MsgVoteResp is captured
for _, em := range env.EnumerateMessages() {
    if em.Msg.Type == raftpb.MsgVoteResp {
        env.InjectMessage(em.Handle) // elect the candidate
    }
}
// alternative: take, inspect, then decide
m, ok := env.TakeMessage(em.Handle)
if ok && m.Type == raftpb.MsgVote {
    env.Nodes[int(m.To-1)].Step(m) // explicit take-and-input form
}
```

### 时间控制

**目标已有入口**

- `RawNode.Tick()`
- `RawNode.TickQuiesced()`
- `Node.Tick()`
- `rafttest InteractionEnv.Tick(idx, num)`
- `rafttest tick-election / tick-heartbeat commands`

**调用示例**

```go
rn.Tick()
```

```go
n.Tick()
```

```go
env.Tick(idx, env.Nodes[idx].Config.ElectionTick)
```

### 随机性控制

**目标已有入口**

- `raft.setRandomizedElectionTimeout(r, v) (package-internal)`
- `raft.SetRandomizedElectionTimeout(rn, v) (exported from raft_test.go; test-binary-only)`
- `rafttest set-randomized-election-timeout command (via InteractionOpts.SetRandomizedElectionTimeout, plumbed only by this module's interaction_test.go)`

**本次生成入口**

- `Config.RandomizedElectionTimeout`
- `InteractionOpts.OnConfig`

**启用与使用范围**

Library-level validated Config option (zero = default random). Same-module tests additionally keep the unvalidated test-file setters and the datadriven rafttest command; the library-facing domain is documented as [ElectionTick, 2*ElectionTick-1].

**仍未覆盖**

- Internal network harness randomness (rafttest/network.go raftNetwork.rand): transport-simulation delay/loss randomness is outside the protocol system boundary; not implemented.

**调用示例**

```go
raft.SetRandomizedElectionTimeout(rn, 5) // same-module tests only
```

```go
c := &raft.Config{ID: 1, ElectionTick: 10, HeartbeatTick: 1, Storage: raft.NewMemoryStorage(), RandomizedElectionTimeout: 10}
rn, err := raft.NewRawNode(c)
if err != nil { t.Fatal(err) }
for i := 0; i < 10; i++ { rn.Tick() }
// rn.Status().RaftState is deterministically StateCandidate at tick 10.
```

```go
c := &raft.Config{ID: 1, ElectionTick: 10, HeartbeatTick: 1, Storage: ms, RandomizedElectionTimeout: 10}
n := raft.StartNode(c, nil)
defer n.Stop() // same deterministic election timing on the async Node path
```

```go
env := rafttest.NewInteractionEnv(&rafttest.InteractionOpts{OnConfig: func(c *raft.Config) { c.RandomizedElectionTimeout = c.ElectionTick }})
snap := raftpb.Snapshot{Metadata: raftpb.SnapshotMetadata{ConfState: raftpb.ConfState{Voters: []uint64{1, 2, 3}}, Index: 2}}
if err := env.AddNodes(3, raft.Config{ElectionTick: 3, HeartbeatTick: 1, MaxSizePerMsg: math.MaxUint64, MaxInflightMsgs: math.MaxInt32}, snap); err != nil { t.Fatal(err) }
if err := env.Tick(1, 3); err != nil { t.Fatal(err) }
// node 2 has deterministically started its election at exactly tick 3.
```

### 生命周期控制

**目标已有入口**

- `Node.Stop()`
- `Node.StartNode(c, peers)`
- `Node.RestartNode(c)`
- `RawNode.NewRawNode(c)`
- `rafttest internal node.pause()/resume()/stop()/restart() (package-internal)`
- `rafttest Node struct fields RawNode/Storage/Config (public, manual reconstruction possible)`

**本次生成入口**

- `InteractionEnv.StopNode`
- `InteractionEnv.RestartNode`
- `InteractionEnv.Handle (stop-node / restart-node commands)`
- `Node.Stopped`

**启用与使用范围**

rafttest.InteractionEnv public API (StopNode/RestartNode, Node.Stopped) plus datadriven commands stop-node/restart-node via InteractionEnv.Handle; no build tags or runtime flags required. Setup: nodes must be created with AddNodes (each node keeps its Config and Storage); StopNode/RestartNode operate on env node indices. Verified by TestInteractionEnvStopRestart (Go) and testdata/lifecycle.txt (datadriven).

**缓存变化与失败语义**

StopNode/RestartNode do not touch env.Messages. DeliverMsgs: for a non-drop recipient whose node is stopped, returns 0 and leaves all its messages in the cache ('not delivering to stopped node N' printed); after RestartNode the same messages can be delivered, after which they are removed from the cache. InjectMessage: a cached message targeting a stopped node returns an error and stays in the cache; on success against a running node the message is removed as before. Drop requests to stopped nodes still remove messages. ClearMessages and per-instance handles are unaffected.

**仍未覆盖**

- Public pause/resume (buffered unavailability) on InteractionEnv for external consumers: not implemented. The synchronous env has no background goroutine to suspend, and StopNode/RestartNode with messages left in flight in the authoritative cache covers the same availability-testing scenarios. The goroutine-based pause/resume remains in the internal network harness, which is unexported and usable by same-package tests only.

**调用示例**

```go
n.Stop()
```

```go
n2 := raft.RestartNode(c) // same *MemoryStorage as the stopped node
```

```go
env := rafttest.NewInteractionEnv(nil)
// ... AddNodes(3, cfg, snap), elect node 1, commit an entry ...
if err := env.StopNode(1); err != nil { t.Fatal(err) } // node 2 down; volatile state discarded
if env.Nodes[1].Stopped { /* RawNode is nil; Storage/Config survive */ }
// The rest of the cluster keeps working; delivery to the stopped node is refused:
if n := env.DeliverMsgs(-1, rafttest.Recipient{ID: 2}); n != 0 { t.Fatal("delivery to stopped node must be refused") }
if err := env.RestartNode(1); err != nil { t.Fatal(err) } // rebuilt from the same Storage
st := env.Nodes[1].Status() // Term/Commit/Applied restored; committed entries are not re-applied
env.DeliverMsgs(-1, rafttest.Recipient{ID: 2}) // in-flight messages now delivered
env.Stabilize()
```

```go
// Datadriven form (via InteractionEnv.Handle):
// stop-node 2
// ----
// ok
//
// restart-node 2
// ----
// ok
```

### 状态观察

**目标已有入口**

- `RawNode.Status()`
- `RawNode.BasicStatus()`
- `RawNode.WithProgress(visitor)`
- `Node.Status()`
- `Storage.Entries/FirstIndex/LastIndex/Term/Snapshot (log range)`
- `rafttest InteractionEnv.RaftLog(idx), handleRaftState(), Status(idx)`

**调用示例**

```go
st := rn.Status()
```

```go
bs := rn.BasicStatus()
```

```go
ents, err := ms.Entries(fi, li+1, math.MaxUint64)
```

### 外部输入

**目标已有入口**

- `Node.Propose(ctx, data)`
- `Node.ProposeConfChange(ctx, cc)`
- `Node.ReadIndex(ctx, rctx)`
- `RawNode.Propose(data)`
- `RawNode.ProposeConfChange(cc)`
- `RawNode.ReadIndex(rctx)`
- `rafttest InteractionEnv.Propose(idx, data)`
- `rafttest InteractionEnv.ProposeConfChange(idx, cc)`

**调用示例**

```go
err := n.Propose(ctx, []byte("cmd"))
```

```go
err := n.ProposeConfChange(ctx, cc)
```

```go
err := n.ReadIndex(ctx, rctx)
```

```go
err := rn.Propose([]byte("cmd"))
```

## Reviewer 最终结论

- 总体结论：`REVISE_AGENT2`
- 阻塞问题：
  - cloneMessage misses Snapshot.Metadata.ConfState nested slices (Voters, Learners, VotersOutgoing, LearnersNext). A test mutating em.Msg.Snapshot.Metadata.ConfState.Voters[0] on an enumerated/taken snapshot would mutate the cached message's snapshot and can alias raft's unstable or storage snapshot. This violates snapshot_safety and contradicts the interface report's 'deep clone of every mutable field' claim. The added TestInteractionEnvMessageSnapshotSafety only mutates Context, Entries[].Data, and Snapshot.Data, so it does not exercise this path.
  - The interface report's message_capture usage example uses raftConfigStub(), an unexported helper, while declaring the facade as externally importable (go.etcd.io/raft/v3/rafttest). An external consumer cannot compile that example, so the usage example does not match the declared consumer scope and setup.
- 非阻塞剩余风险：
  - env.Messages remains an exported field while msgIDs is private; the facade keeps them aligned only through its own helpers. All in-tree mutation paths (ProcessReady, SendSnapshot, ProcessAppendThread, ProcessApplyThread, DeliverMsgs) are rewired, and direct external splicing of env.Messages is documented as unsupported, but such direct mutation can still desynchronize handles and make EnumerateMessages mis-index or panic.
