# hashicorp-raft 测试接口清单

本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。
详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。

## 快速接口矩阵

| 能力 | 修改前状态 | 目标已有入口 | 本次生成入口 | 当前结论 |
|---|---|---|---|---|
| 消息捕获 | `PATCHABLE` | `Transport.Consumer() inbound channel (transport.go:34)`<br>`Transport.AppendEntries / RequestVote / InstallSnapshot / TimeoutNow / RequestPreVote (transport.go:44-66, 74-77)`<br>`Transport.AppendEntriesPipeline (transport.go:41, 112-123)`<br>等 5 项 | — | 尚需低侵入补充 |
| 消息注入 | `PATCHABLE` | `RPC.Respond (transport.go:25-27)`<br>`Transport consumer channel (injection target for inbound requests)`<br>`Transport send methods and AppendPipeline (injection targets for outbound requests)`<br>等 4 项 | — | 尚需低侵入补充 |
| 时间控制 | `INVASIVE` | `time.After / time.NewTimer usage: util.go:39 (randomTimeout), api.go:831,861,1058 (Apply/Barrier/Restore timeouts), raft.go:163-353 (heartbeat/election), replication.go:169,402,495, snapshot.go:75`<br>`time.Now / time.Since: api.go:1128 (LastContact), api.go:1215 (Stats), raft.go:221 (contact check), future.go:135 (dispatch), replication.go:416 (LastContact observation)`<br>`Config.HeartbeatTimeout / ElectionTimeout / CommitTimeout / LeaderLeaseTimeout / SnapshotInterval (config.go:149-205) with ReloadConfig (api.go:717-741)` | — | INVASIVE |
| 随机性控制 | `PATCHABLE` | `randomTimeout (util.go:34) used at raft.go:163, 217, 310, 353, 426; replication.go:169, 402, 495; snapshot.go:75`<br>`package init seeding of global math/rand (util.go:18-21)`<br>`NewInmemAddr / generateUUID (inmem_transport.go:15-17, util.go:59-71)` | — | 尚需低侵入补充 |
| 生命周期控制 | `SUPPORTED` | `Raft.Shutdown (api.go:1012)`<br>`Raft.NewRaft reconstruction (api.go:500)`<br>`cluster.Close / shutdown helpers in package testing support` | — | 直接复用目标已有接口 |
| 状态观察 | `SUPPORTED` | `Raft.State (api.go:1102)`<br>`Raft.Stats (api.go:1160)`<br>`Raft.CurrentTerm / LastIndex / CommitIndex / AppliedIndex (api.go:1221-1247)`<br>等 8 项 | — | 直接复用目标已有接口 |
| 外部输入 | `SUPPORTED` | `Raft.Apply (api.go:819)`<br>`Raft.ApplyLog (api.go:826)`<br>`Raft.AddVoter / AddNonvoter / RemoveServer / DemoteVoter (api.go:946-1007)`<br>等 4 项 | — | 直接复用目标已有接口 |

## 接口详情与示例

### 消息捕获

**目标已有入口**

- `Transport.Consumer() inbound channel (transport.go:34)`
- `Transport.AppendEntries / RequestVote / InstallSnapshot / TimeoutNow / RequestPreVote (transport.go:44-66, 74-77)`
- `Transport.AppendEntriesPipeline (transport.go:41, 112-123)`
- `Transport.SetHeartbeatHandler (transport.go:59-63)`
- `Observer/RegisterObserver (observer.go:106-118)`

### 消息注入

**目标已有入口**

- `RPC.Respond (transport.go:25-27)`
- `Transport consumer channel (injection target for inbound requests)`
- `Transport send methods and AppendPipeline (injection targets for outbound requests)`
- `processRPC / processHeartbeat dispatch inside Raft (raft.go:1390-1436)`

### 时间控制

**目标已有入口**

- `time.After / time.NewTimer usage: util.go:39 (randomTimeout), api.go:831,861,1058 (Apply/Barrier/Restore timeouts), raft.go:163-353 (heartbeat/election), replication.go:169,402,495, snapshot.go:75`
- `time.Now / time.Since: api.go:1128 (LastContact), api.go:1215 (Stats), raft.go:221 (contact check), future.go:135 (dispatch), replication.go:416 (LastContact observation)`
- `Config.HeartbeatTimeout / ElectionTimeout / CommitTimeout / LeaderLeaseTimeout / SnapshotInterval (config.go:149-205) with ReloadConfig (api.go:717-741)`

### 随机性控制

**目标已有入口**

- `randomTimeout (util.go:34) used at raft.go:163, 217, 310, 353, 426; replication.go:169, 402, 495; snapshot.go:75`
- `package init seeding of global math/rand (util.go:18-21)`
- `NewInmemAddr / generateUUID (inmem_transport.go:15-17, util.go:59-71)`

### 生命周期控制

**目标已有入口**

- `Raft.Shutdown (api.go:1012)`
- `Raft.NewRaft reconstruction (api.go:500)`
- `cluster.Close / shutdown helpers in package testing support`

**调用示例**

```go
if err := r.Shutdown().Error(); err != nil { t.Fatal(err) }
r2, err := raft.NewRaft(cfg, fsm, logs, stable, snaps, trans2) // same LocalID and stores
if err != nil { t.Fatal(err) }
```

### 状态观察

**目标已有入口**

- `Raft.State (api.go:1102)`
- `Raft.Stats (api.go:1160)`
- `Raft.CurrentTerm / LastIndex / CommitIndex / AppliedIndex (api.go:1221-1247)`
- `Raft.LeaderWithID / Leader / LastContact / LeaderCh (api.go:786-802, 1128, 1117)`
- `Raft.GetConfiguration (api.go:897) and ConfigurationFuture`
- `Raft.ReloadableConfig (api.go:749)`
- `NewObserver / RegisterObserver / DeregisterObserver (observer.go:87-118)`
- `caller-owned LogStore for log ranges (LogStore.GetLog/FirstIndex/LastIndex, log.go)`

**调用示例**

```go
st := r.Stats() // map[string]string with "state", "term", "commit_index", "applied_index"
state := r.State() // raft.Follower/Candidate/Leader
cfgF := r.GetConfiguration()
cfg := cfgF.Configuration() // raft.Configuration with Servers
```

### 外部输入

**目标已有入口**

- `Raft.Apply (api.go:819)`
- `Raft.ApplyLog (api.go:826)`
- `Raft.AddVoter / AddNonvoter / RemoveServer / DemoteVoter (api.go:946-1007)`
- `Raft.AddPeer / RemovePeer deprecated (api.go:908-936)`

**调用示例**

```go
c := raft.MakeCluster(3, t, nil)
leader := c.Leader() // *raft.Raft
future := leader.Apply([]byte("set x=1"), 0)
if err := future.Error(); err != nil { t.Fatal(err) }
idx, resp := future.Index(), future.Response()
```

```go
c := raft.MakeCluster(3, t, nil)
leader := c.Leader()
if err := leader.AddVoter("srv-4", "127.0.0.1:9004", 0, 0).Error(); err != nil { t.Fatal(err) }
```
