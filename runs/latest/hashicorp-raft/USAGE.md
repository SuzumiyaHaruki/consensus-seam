# hashicorp-raft 测试接口清单

本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。
详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。

## 快速接口矩阵

| 能力 | 修改前状态 | 目标已有入口 | 本次生成入口 | 当前结论 |
|---|---|---|---|---|
| 消息捕获 | `PATCHABLE` | `Transport interface methods and Consumer() channel (existing primitives)`<br>`Harness-defined controlled transport: Enumerate/Take/Drop/Clear/Deliver (proposed, no target core changes)` | — | 尚需低侵入补充 |
| 消息注入 | `PATCHABLE` | `Harness-defined controlled transport Deliver/input operations (proposed, combined single-call or separated Take-plus-input)` | — | 尚需低侵入补充 |
| 时间控制 | `INVASIVE` | `randomTimeout`<br>`runFollower`<br>`Raft.heartbeat`<br>等 4 项 | — | INVASIVE |
| 随机性控制 | `PATCHABLE` | `Config.Rand *rand.Rand (proposed injectable per-node source)` | — | 尚需低侵入补充 |
| 生命周期控制 | `SUPPORTED` | `Raft.Shutdown`<br>`shutdownFuture.Error`<br>`NewRaft` | — | 直接复用目标已有接口 |
| 状态观察 | `SUPPORTED` | `Raft.State / Raft.Stats / Raft.CurrentTerm / Raft.CommitIndex / Raft.AppliedIndex / Raft.LastIndex / Raft.LastContact / Raft.LeaderWithID`<br>`Raft.GetConfiguration (ConfigurationFuture)`<br>`InmemStore.FirstIndex/LastIndex/GetLog/GetUint64 and InmemSnapshotStore.List (caller-owned stores)` | — | 直接复用目标已有接口 |
| 外部输入 | `SUPPORTED` | `Raft.Apply / Raft.ApplyLog`<br>`Raft.AddVoter / Raft.AddNonvoter / Raft.RemoveServer / Raft.DemoteVoter` | — | 直接复用目标已有接口 |

## 接口详情与示例

### 消息捕获

**目标已有入口**

- `Transport interface methods and Consumer() channel (existing primitives)`
- `Harness-defined controlled transport: Enumerate/Take/Drop/Clear/Deliver (proposed, no target core changes)`

### 消息注入

**目标已有入口**

- `Harness-defined controlled transport Deliver/input operations (proposed, combined single-call or separated Take-plus-input)`

### 时间控制

No Clock or Tick abstraction exists anywhere in the module; all protocol timing is dispersed wall-clock use (randomTimeout -> time.After for election/heartbeat/commit/snapshot staggering, leader-lease timers, replication backoff, time.Now last-contact tracking). There is no single seam a test can advance deterministically.

### 随机性控制

**目标已有入口**

- `Config.Rand *rand.Rand (proposed injectable per-node source)`

### 生命周期控制

**目标已有入口**

- `Raft.Shutdown`
- `shutdownFuture.Error`
- `NewRaft`

**调用示例**

```go
// Requires: r *raft.Raft, conf *raft.Config, fsm raft.FSM, logs raft.LogStore, stable raft.StableStore, snaps raft.SnapshotStore, trans raft.Transport
// Shutdown is terminal for the instance; the test reconnects/recreates the transport for the next cycle.
if err := r.Shutdown().Error(); err != nil { /* handle */ }
r2, err := raft.NewRaft(conf, fsm, logs, stable, snaps, trans)
if err != nil { /* handle */ }
fmt.Println(r2.State())
```

### 状态观察

**目标已有入口**

- `Raft.State / Raft.Stats / Raft.CurrentTerm / Raft.CommitIndex / Raft.AppliedIndex / Raft.LastIndex / Raft.LastContact / Raft.LeaderWithID`
- `Raft.GetConfiguration (ConfigurationFuture)`
- `InmemStore.FirstIndex/LastIndex/GetLog/GetUint64 and InmemSnapshotStore.List (caller-owned stores)`

**调用示例**

```go
// Requires: r *raft.Raft
fmt.Println(r.State(), r.CurrentTerm(), r.CommitIndex(), r.AppliedIndex(), r.Stats()["state"])
```

```go
// Requires: r *raft.Raft
future := r.GetConfiguration()
if err := future.Error(); err != nil { /* handle */ }
fmt.Println(future.Configuration().Servers, future.Index())
```

### 外部输入

**目标已有入口**

- `Raft.Apply / Raft.ApplyLog`
- `Raft.AddVoter / Raft.AddNonvoter / Raft.RemoveServer / Raft.DemoteVoter`

**调用示例**

```go
// Requires: r *raft.Raft
future := r.Apply([]byte("set-x=1"), 10*time.Second)
if err := future.Error(); err != nil { /* handle */ }
fmt.Println(future.Response())
```

```go
// Requires: leader *raft.Raft
f := leader.AddVoter(raft.ServerID("node-2"), raft.ServerAddress("10.0.0.2:8300"), 0, 10*time.Second)
if err := f.Error(); err != nil { /* handle */ }
fmt.Println(f.Index())
```
