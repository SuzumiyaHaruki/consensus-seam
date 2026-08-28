# hashicorp-raft 测试接口清单

本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。
详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。

## 快速接口矩阵

| 能力 | 修改前状态 | 目标已有入口 | 本次生成入口 | 当前结论 |
|---|---|---|---|---|
| 消息捕获 | `PATCHABLE` | `InmemTransport.Consumer`<br>`RPC.Respond`<br>`inmemPipeline.Consumer` | — | 尚需低侵入补充 |
| 消息注入 | `PATCHABLE` | `RPC.Respond`<br>`InmemTransport.AppendEntries`<br>`InmemTransport.RequestVote`<br>等 7 项 | — | 尚需低侵入补充 |
| 时间控制 | `INVASIVE` | `randomTimeout`<br>`Raft.runFollower`<br>`Raft.leaderLoop`<br>等 5 项 | — | INVASIVE |
| 随机性控制 | `SUPPORTED` | `math/rand.Seed (via randomTimeout)`<br>`Config.ElectionTimeout`<br>`Config.HeartbeatTimeout`<br>等 5 项 | — | 直接复用目标已有接口 |
| 生命周期控制 | `SUPPORTED` | `Raft.Shutdown`<br>`NewRaft`<br>`InmemTransport.Connect`<br>等 7 项 | — | 直接复用目标已有接口 |
| 状态观察 | `SUPPORTED` | `Raft.State`<br>`Raft.Stats`<br>`Raft.LeaderWithID`<br>等 14 项 | — | 直接复用目标已有接口 |
| 外部输入 | `SUPPORTED` | `Raft.Apply`<br>`Raft.ApplyLog`<br>`Raft.Barrier`<br>等 15 项 | — | 直接复用目标已有接口 |

## 接口详情与示例

### 消息捕获

**目标已有入口**

- `InmemTransport.Consumer`
- `RPC.Respond`
- `inmemPipeline.Consumer`

**调用示例**

```go
rpcCh := trans.Consumer() // trans is the *raft.InmemTransport of the target node
rpc := <-rpcCh // take one captured RPC; the sender stays blocked on rpc.RespChan
req := rpc.Command.(*raft.AppendEntriesRequest)
if req.Term != wantTerm { t.Fatalf("unexpected message: %+v", req) }
```

```go
// enumerate/clear: drain without responding
for {
    select {
    case rpc := <-rpcCh:
        held = append(held, rpc) // or discard to drop
    default:
        goto done
    }
}
done:
```

### 消息注入

**目标已有入口**

- `RPC.Respond`
- `InmemTransport.AppendEntries`
- `InmemTransport.RequestVote`
- `InmemTransport.RequestPreVote`
- `InmemTransport.InstallSnapshot`
- `InmemTransport.TimeoutNow`
- `inmemPipeline.AppendEntries`

**调用示例**

```go
rpc := <-trans.Consumer() // take from the same capture cache
resp := &raft.AppendEntriesResponse{Term: 1, Success: true, LastLog: 5}
rpc.Respond(resp, nil) // normal response injection; sender's makeRPC completes
```

```go
// request re-delivery (in-package tests):
trans.consumerCh <- rpc // requeue the captured RPC so the node's main loop processes it
```

### 时间控制

No Tick or injectable Clock exists; all timers are created and consumed inside the main loops from wall clock, so tests cannot deterministically advance protocol-observed time without intrusive restructuring.

### 随机性控制

**目标已有入口**

- `math/rand.Seed (via randomTimeout)`
- `Config.ElectionTimeout`
- `Config.HeartbeatTimeout`
- `Config.CommitTimeout`
- `Config.SnapshotInterval`

**调用示例**

```go
math/rand.Seed(42) // fix the shared source used by randomTimeout
conf := raft.DefaultConfig()
conf.ElectionTimeout = 200 * time.Millisecond // deterministic lower bound; draw range [200ms, 400ms)
```

```go
// same seed + same timeouts => same random election/heartbeat/snapshot staggering sequence
```

### 生命周期控制

**目标已有入口**

- `Raft.Shutdown`
- `NewRaft`
- `InmemTransport.Connect`
- `InmemTransport.Disconnect`
- `InmemTransport.DisconnectAll`
- `cluster.Partition`
- `cluster.FullyConnect`

**调用示例**

```go
f := raft.Shutdown()
if err := f.Error(); err != nil { t.Fatal(err) } // node unavailable
// rejoin the same logical node from the same caller-owned stores:
r2, err := raft.NewRaft(conf, fsm, store, store, snaps, trans)
if err != nil { t.Fatal(err) }
```

```go
trans.Disconnect(peerAddr) // isolate a running node
...
trans.Connect(peerAddr, peerTrans) // bring it back
```

### 状态观察

**目标已有入口**

- `Raft.State`
- `Raft.Stats`
- `Raft.LeaderWithID`
- `Raft.CurrentTerm`
- `Raft.LastIndex`
- `Raft.CommitIndex`
- `Raft.AppliedIndex`
- `Raft.LastContact`
- `Raft.GetConfiguration`
- `Raft.ReloadableConfig`
- `Raft.LeaderCh`
- `Raft.RegisterObserver`
- `NewObserver`
- `InmemStore.GetLog`

**调用示例**

```go
state := raft.State()
if state != raft.Leader { t.Fatalf("not leader: %v", state) }
stats := raft.Stats()
commit := stats["commit_index"]
```

```go
cf := raft.GetConfiguration()
if err := cf.Error(); err != nil { t.Fatal(err) }
cfg := cf.Configuration()
_ = cfg.Servers
```

```go
obsCh := make(chan raft.Observation, 64)
obs := raft.NewObserver(obsCh, false, nil)
raft.RegisterObserver(obs)
defer raft.DeregisterObserver(obs)
o := <-obsCh
_ = o.Raft // instance reference; o.Data is a typed copy
```

### 外部输入

**目标已有入口**

- `Raft.Apply`
- `Raft.ApplyLog`
- `Raft.Barrier`
- `Raft.VerifyLeader`
- `Raft.AddVoter`
- `Raft.AddNonvoter`
- `Raft.RemoveServer`
- `Raft.DemoteVoter`
- `Raft.AddPeer`
- `Raft.RemovePeer`
- `Raft.Snapshot`
- `Raft.Restore`
- `Raft.LeadershipTransfer`
- `Raft.LeadershipTransferToServer`
- `Raft.BootstrapCluster`

**调用示例**

```go
leader := c.Leader() // *raft.Raft from raft.MakeCluster
f := leader.Apply([]byte("cmd"), 10*time.Second)
if err := f.Error(); err != nil { t.Fatal(err) }
idx := f.Index()
```

```go
add := leader.AddVoter(raft.ServerID("s4"), raft.ServerAddress("addr4"), 0, 0)
if err := add.Error(); err != nil { t.Fatal(err) }
_ = add.Index()
```
