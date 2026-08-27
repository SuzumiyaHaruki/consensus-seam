# etcd-raft 测试接口清单

本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。
详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。

## 快速接口矩阵

| 能力         | 修改前状态    | 目标已有入口                                                                                                                                                                                                                                                                                                                                                                                                | 本次生成入口                                                                       | 当前结论                  |
| ------------ | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------- |
| 消息捕获     | `SUPPORTED` | `RawNode.Ready (rawnode.go:133), RawNode.HasReady (rawnode.go:453), RawNode.Advance (rawnode.go:482)Node.Ready() <-chan Ready (node.go:552), Node.Advance (node.go:554)``rafttest InteractionEnv.ProcessReady (rafttest/interaction_env_handler_process_ready.go:45), env.Messages field (rafttest/interaction_env.go:52), Node.AppendWork/ApplyWork fields (rafttest/interaction_env.go:42-43)`等 4 项 | —                                                                                 | 直接复用目标已有接口      |
| 消息注入     | `SUPPORTED` | `rafttest InteractionEnv.DeliverMsgs (rafttest/interaction_env_handler_deliver_msgs.go:81)Node.Step (node.go:478)``RawNode.Step (rawnode.go:118)`                                                                                                                                                                                                                                                       | —                                                                                 | 直接复用目标已有接口      |
| 时间控制     | `SUPPORTED` | `Node.Tick (node.go:463)RawNode.Tick (rawnode.go:64), RawNode.TickQuiesced (rawnode.go:78, deprecated)``rafttest InteractionEnv.Tick (rafttest/interaction_env_handler_tick.go:34), tick-election / tick-heartbeat handlers`等 4 项                                                                                                                                                                     | —                                                                                 | 直接复用目标已有接口      |
| 随机性控制   | `PATCHABLE` | `raft.setRandomizedElectionTimeout / raft.SetRandomizedElectionTimeout (raft_test.go:4092-4100, test build only)rafttest InteractionOpts.SetRandomizedElectionTimeout (rafttest/interaction_env.go:31-33) and set-randomized-election-timeout handler (rafttest/interaction_env_handler_set_randomized_election_timeout.go:24)``raft.reset -> resetRandomizedElectionTimeout (raft.go:793, 2049)`       | `Config.RandomizedElectionTimeouthandleAddNodes randomized-election-timeout arg` | 已生成接口；覆盖 4 条路径 |
| 生命周期控制 | `SUPPORTED` | `Node.Stop (node.go:336)StartNode (node.go:276)``RestartNode (node.go:286)`等 5 项                                                                                                                                                                                                                                                                                                                      | —                                                                                 | 直接复用目标已有接口      |
| 状态观察     | `SUPPORTED` | `Node.Status (node.go:574)RawNode.Status (rawnode.go:498), RawNode.BasicStatus (rawnode.go:505), RawNode.WithProgress (rawnode.go:521)``rafttest InteractionEnv.Status (rafttest/interaction_env_handler_status.go:33), handleRaftState, RaftLog (rafttest/interaction_env_handler_raft_log.go:33)`                                                                                                     | —                                                                                 | 直接复用目标已有接口      |
| 外部输入     | `SUPPORTED` | `Node.Propose (node.go:474)Node.ProposeConfChange (node.go:495)``Node.ReadIndex (node.go:613)`等 8 项                                                                                                                                                                                                                                                                                                   | —                                                                                 | 直接复用目标已有接口      |

## 接口详情与示例

### 消息捕获

**目标已有入口**

- `RawNode.Ready (rawnode.go:133), RawNode.HasReady (rawnode.go:453), RawNode.Advance (rawnode.go:482)`
- `Node.Ready() <-chan Ready (node.go:552), Node.Advance (node.go:554)`
- `rafttest InteractionEnv.ProcessReady (rafttest/interaction_env_handler_process_ready.go:45), env.Messages field (rafttest/interaction_env.go:52), Node.AppendWork/ApplyWork fields (rafttest/interaction_env.go:42-43)`
- `rafttest InteractionEnv.ProcessAppendThread (rafttest/interaction_env_handler_process_append_thread.go:47), ProcessApplyThread (rafttest/interaction_env_handler_process_apply_thread.go:46)`

**调用示例**

```go
env := rafttest.NewInteractionEnv(nil)
env.AddNodes(3, cfg, snap)
env.ProcessReady(0)      // Ready.Messages -> env.Messages
msgs := env.Messages     // inspect cached instances, order preserved
env.DeliverMsgs(-1, rafttest.Recipient{ID: 2}) // test-controlled continuation/removal
```

### 消息注入

**目标已有入口**

- `rafttest InteractionEnv.DeliverMsgs (rafttest/interaction_env_handler_deliver_msgs.go:81)`
- `Node.Step (node.go:478)`
- `RawNode.Step (rawnode.go:118)`

**调用示例**

```go
// rafttest env: select and deliver cached messages
env.DeliverMsgs(raftpb.MsgApp, rafttest.Recipient{ID: 2})
env.DeliverMsgs(-1, rafttest.Recipient{ID: 3, Drop: true})
// direct public API with a captured message
n.Step(context.Background(), msg) // Node path
rn.Step(msg)                      // RawNode path
```

### 时间控制

**目标已有入口**

- `Node.Tick (node.go:463)`
- `RawNode.Tick (rawnode.go:64), RawNode.TickQuiesced (rawnode.go:78, deprecated)`
- `rafttest InteractionEnv.Tick (rafttest/interaction_env_handler_tick.go:34), tick-election / tick-heartbeat handlers`
- `raft.tickElection (raft.go:850), raft.tickHeartbeat (raft.go:862)`

**调用示例**

```go
rn.Tick()          // RawNode: exactly one logical tick
n.Tick()           // Node: one tick (buffered tickc)
env.Tick(idx, 3)   // rafttest: three ticks on node idx
// tick-election 3  // datadriven: env.Tick(idx, ElectionTick)
```

### 随机性控制

**目标已有入口**

- `raft.setRandomizedElectionTimeout / raft.SetRandomizedElectionTimeout (raft_test.go:4092-4100, test build only)`
- `rafttest InteractionOpts.SetRandomizedElectionTimeout (rafttest/interaction_env.go:31-33) and set-randomized-election-timeout handler (rafttest/interaction_env_handler_set_randomized_election_timeout.go:24)`
- `raft.reset -> resetRandomizedElectionTimeout (raft.go:793, 2049)`

**本次生成入口**

- `Config.RandomizedElectionTimeout`
- `handleAddNodes randomized-election-timeout arg`

**启用与使用范围**

Set Config.RandomizedElectionTimeout before calling NewRawNode/StartNode/RestartNode; the value is fixed at node construction and re-applied on every state change. For rafttest, pass randomized-election-timeout=<n></n> to add-nodes. The existing test-build-only raft.SetRandomizedElectionTimeout (raft_test.go:4098) and the set-randomized-election-timeout command remain available to in-module tests but stay transient.

**调用示例**

```go
// module-internal test usage (test build of the raft package):
env := rafttest.NewInteractionEnv(&rafttest.InteractionOpts{
    SetRandomizedElectionTimeout: raft.SetRandomizedElectionTimeout,
})
// datadriven command:
// set-randomized-election-timeout 1 timeout=5
```

```go
cfg := &raft.Config{ID: 1, ElectionTick: 10, HeartbeatTick: 1, Storage: raft.NewMemoryStorage(), RandomizedElectionTimeout: 10}
rn, err := raft.NewRawNode(cfg)
for i := 0; i < 9; i++ { rn.Tick() } // still StateFollower
rn.Tick()                            // election fires on exactly the 10th tick, repeatably
```

```go
cfg.RandomizedElectionTimeout = 10
n := raft.StartNode(cfg, peers) // same fixed value applies on the Node path; survives state changes
```

```go
// rafttest datadriven:
// add-nodes 1 voters=(1) index=2 randomized-election-timeout=5
// tick 1 5   // election fires on exactly the 5th tick (ElectionTick=3 in the stub)
```

### 生命周期控制

**目标已有入口**

- `Node.Stop (node.go:336)`
- `StartNode (node.go:276)`
- `RestartNode (node.go:286)`
- `RawNode has no stop/restart API; availability is the caller's scheduling (test driver stops calling Ready/Tick)`
- `rafttest node harness (same-package only): pause (rafttest/node.go:151), resume (rafttest/node.go:156), stop (rafttest/node.go:122), restart (rafttest/node.go:131)`

**调用示例**

```go
n := raft.StartNode(cfg, peers)
// make unavailable:
n.Stop()
// restore availability (new instance reconstructed from cfg.Storage):
n = raft.RestartNode(cfg)
```

### 状态观察

**目标已有入口**

- `Node.Status (node.go:574)`
- `RawNode.Status (rawnode.go:498), RawNode.BasicStatus (rawnode.go:505), RawNode.WithProgress (rawnode.go:521)`
- `rafttest InteractionEnv.Status (rafttest/interaction_env_handler_status.go:33), handleRaftState, RaftLog (rafttest/interaction_env_handler_raft_log.go:33)`

**调用示例**

```go
st := n.Status()               // role, term, commit, applied, lead, config, progress
b := rn.BasicStatus()           // allocation-free basics
rn.WithProgress(func(id uint64, typ raft.ProgressType, pr tracker.Progress) { /* inspect */ })
```

### 外部输入

**目标已有入口**

- `Node.Propose (node.go:474)`
- `Node.ProposeConfChange (node.go:495)`
- `Node.ReadIndex (node.go:613)`
- `RawNode.Propose (rawnode.go:90)`
- `RawNode.ProposeConfChange (rawnode.go:101)`
- `RawNode.ReadIndex (rawnode.go:561)`
- `rafttest InteractionEnv.Propose / propose-conf-change handlers`
- `Control-only entrypoints (not workload): Node.Campaign, Node.TransferLeadership, Node.ForgetLeader, RawNode.Campaign/TransferLeader/ForgetLeader`

**调用示例**

```go
rn := raft.NewRawNode(cfg)
if err := rn.Propose([]byte("cmd")); err != nil { /* handle */ }
if err := rn.ProposeConfChange(cc); err != nil { /* handle */ }
rn.ReadIndex(rctx) // read state arrives via Ready.ReadStates
```

```go
n := raft.StartNode(cfg, peers)
if err := n.Propose(ctx, []byte("cmd")); err != nil { /* handle */ }
if err := n.ProposeConfChange(ctx, cc); err != nil { /* handle */ }
if err := n.ReadIndex(ctx, rctx); err != nil { /* handle */ }
```

## Reviewer 最终结论

- 总体结论：`PASS`
- 非阻塞剩余风险：
  - For external consumers, an out-of-domain non-zero RandomizedElectionTimeout surfaces as a panic from newRaft via NewRawNode/StartNode/RestartNode rather than a returned error; this matches the existing Config validation style for all other Config errors and is documented in the interface notes.
