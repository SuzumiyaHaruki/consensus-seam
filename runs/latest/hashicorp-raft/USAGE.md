# hashicorp-raft 测试接口清单

本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。
详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。

## 快速接口矩阵

| 能力 | 修改前状态 | 目标已有入口 | 本次生成入口 | 当前结论 |
|---|---|---|---|---|
| 消息捕获 | `PATCHABLE` | `Transport.Consumer`<br>`Transport.AppendEntries`<br>`Transport.RequestVote`<br>等 8 项 | `NewMessageController`<br>`MessageController.SetControlled`<br>`MessageController.Pending`<br>等 10 项 | 已生成接口；覆盖 6 条路径 |
| 消息注入 | `PATCHABLE` | `InmemTransport.makeRPC`<br>`RPC.Respond` | `MessageController.Inject`<br>`ErrMessageNotPending`<br>`ErrTargetUnavailable`<br>等 4 项 | 已生成接口；覆盖 6 条路径 |
| 时间控制 | `PATCHABLE` | `Raft.runFollower`<br>`Raft.runCandidate`<br>`Raft.leaderLoop`<br>等 4 项 | `TimeController`<br>`NewTimeController`<br>`TimeController.Advance`<br>等 7 项 | 已生成接口；覆盖 7 条路径，未覆盖 4 条 |
| 随机性控制 | `PATCHABLE` | `randomTimeout`<br>`Raft.runCandidate` | `NewRandomController`<br>`RandomController.Choices` | 已生成接口；覆盖 4 条路径 |
| 生命周期控制 | `PATCHABLE` | `Raft.Shutdown`<br>`NewRaft` | `NewLifecycleController`<br>`LifecycleController.Pause`<br>`LifecycleController.Resume`<br>等 11 项 | 已生成接口；覆盖 7 条路径，未覆盖 4 条 |
| 状态观察 | `SUPPORTED` | `Raft.State`<br>`Raft.Stats`<br>`Raft.LeaderWithID`<br>等 14 项 | — | 直接复用目标已有接口 |
| 外部输入 | `SUPPORTED` | `Raft.Apply`<br>`Raft.ApplyLog`<br>`Raft.AddVoter`<br>等 6 项 | — | 直接复用目标已有接口 |

## 消息控制调用顺序

1. 调用报告列出的 NewMessageController 构造器并完成目标接线。
2. 调用 Pending，获得可检查的消息深拷贝快照和稳定 Handle。
3. 测试代码根据目标原生消息字段选择实例；ConsensusSeam 不决定选择策略。
4. 将同一 Handle 交给 Drop 或 Inject；需要全部丢弃时调用 Clear。
5. 根据下方记录的接受点、错误类别和缓存变化决定后续测试动作。

## 接口详情与示例

### 消息捕获

**目标已有入口**

- `Transport.Consumer`
- `Transport.AppendEntries`
- `Transport.RequestVote`
- `Transport.RequestPreVote`
- `Transport.InstallSnapshot`
- `Transport.TimeoutNow`
- `Transport.AppendEntriesPipeline`
- `InmemTransport.Connect`

**本次生成入口**

- `NewMessageController`
- `MessageController.SetControlled`
- `MessageController.Pending`
- `MessageController.Drop`
- `MessageController.Clear`
- `PendingMessage`
- `MessageHandle`
- `MessageKind`
- `NewControlledTransport`
- `ControlledTransport`

**启用与使用范围**

Focused same-package tests in message_controller_test.go: round trip incl. stream snapshot deep-copy, drop/clear/errors, target unavailable, two-node end-to-end election and commit, concurrent single-delivery, and the new TestMessageControllerDropAndInjectPreserveOrder (Drop and successful Inject of a middle entry leave the acceptance order of the remaining entries intact) and TestMessageControllerClosedOwnerRebind (closed-owner Inject fails deterministically with ErrMessageNotAccepted and preserves the entry; re-binding the entry to a fresh wrapper of the same node makes the same handle deliverable again).

**缓存实例引用**

One MessageController per test cluster; each node's ControlledTransport binds to it. A MessageHandle identifies one concrete entry and remains stable while pending; identities are never reused after removal.

**目标绑定方式**

The captured target address is resolved at Inject through the owning wrapper's base InmemTransport peers map, the same routing table InmemTransport.makeRPC uses; ServerIDs come from the transport call arguments (target id) and the wrapper's local ID (source).

**缓存变化与失败语义**

Capture appends one entry per outbound transport call (broadcast expands per concrete target in stable controller acceptance order). Drop removes one entry and Clear removes all; removal is order-preserving (append-slice delete), so Drop, Clear, and Inject never reorder the remaining entries. A successful Inject removes the request entry, invalidates its handle, and later records the protocol response as a new pending entry with a fresh handle. Copy or stream-buffer failures are returned to the caller and register nothing in the cache. Handles are never reused and entries are never silently evicted, retargeted, or reordered.

**调用示例**

```go
// Requires: t1, t2 *raft.InmemTransport; addr1, addr2 raft.ServerAddress
ctl := raft.NewMessageController()
w1 := raft.NewControlledTransport(t1, ctl, raft.ServerID("node1"))
w2 := raft.NewControlledTransport(t2, ctl, raft.ServerID("node2"))
w1.Connect(addr2, w2)
w2.Connect(addr1, w1)
ctl.SetControlled(true)
```

```go
// Requires: ctl *raft.MessageController
pending := ctl.Pending()
for _, pm := range pending {
    if pm.Kind == raft.MessageKindInstallSnapshotRequest {
        _ = pm.Stream // deep-copied buffered snapshot stream
    }
    if pm.Kind == raft.MessageKindAppendEntriesRequest {
        _ = pm.Message.AppendEntriesRequest.Term
    }
}
```

```go
// Requires: ctl *raft.MessageController; h raft.MessageHandle
if err := ctl.Drop(h); err != nil { /* ErrMessageNotPending */ }
ctl.Clear()
```

### 消息注入

**本次生成入口**

- `MessageController.Inject`
- `ErrMessageNotPending`
- `ErrTargetUnavailable`
- `ErrMessageNotAccepted`

**启用与使用范围**

Covered by message_controller_test.go: round trip (request inject, response capture and inject), drop/clear/error classification, target-unavailable preservation, the two-node end-to-end Raft election/commit driven purely by Inject, TestMessageControllerConcurrentInjectDeliversOnce, TestMessageControllerClosedOwnerRebind (deterministic closed-owner ErrMessageNotAccepted with entry preservation, then successful delivery of the same handle after rebind to a fresh wrapper), and TestLifecycleControllerRestartKeepsPendingInjectible in lifecycle_control_test.go (TimeoutNow captured before Crash, Restart re-binds it, Inject delivers through the live peer ingress, the response is captured, and the handle is invalidated on acceptance).

**缓存实例引用**

One controller instance owns the cache; capture and injection operate on the same instance and the same declared end-to-end path per message; LifecycleController.Restart re-binds entries of a restarted node to its fresh wrapper on that same instance.

**目标绑定方式**

The captured ServerAddress is resolved against the owning wrapper's base InmemTransport peers map at Inject time (identifier arithmetic alone is never used); the resolved peer's consumerCh is the normal request ingress for that direction. After Restart the fresh wrapper wraps the same base transport, so re-connected routes resolve identically.

**缓存变化与失败语义**

Successful Inject removes the request entry, invalidates its handle, and then records the protocol response as a new pending entry. Invalid handle, unavailable target, explicit non-acceptance, or a closed owning transport return an error and preserve the entry and handle; a closed-owner refusal is deterministic (no race against a permanently-ready closed channel). Re-binding the entry to a fresh wrapper of the same node (LifecycleController.Restart) restores delivery. Later protocol failure never restores an accepted entry. Concurrent Inject calls on one handle deliver exactly once: one call succeeds, the others are refused with ErrMessageNotPending while the in-flight delivery decides the entry's fate.

**调用示例**

```go
// Requires: ctl *raft.MessageController; h raft.MessageHandle
if err := ctl.Inject(h); err != nil {
    if errors.Is(err, raft.ErrTargetUnavailable) { /* target disconnected; entry preserved */ }
    if errors.Is(err, raft.ErrMessageNotAccepted) { /* enqueue refused or owner closed; entry preserved */ }
    if errors.Is(err, raft.ErrMessageNotPending) { /* already delivered/dropped/cleared */ }
}
```

```go
// Requires: ctl *raft.MessageController
for _, pm := range ctl.Pending() {
    if pm.Kind == raft.MessageKindRequestVoteRequest {
        if err := ctl.Inject(pm.Handle); err != nil { /* classify */ }
    }
}
```

### 时间控制

**本次生成入口**

- `TimeController`
- `NewTimeController`
- `TimeController.Advance`
- `TimeController.Clock`
- `TimeController.Register`
- `Clock`
- `Config.Clock`

**启用与使用范围**

Config.Clock = tc.Clock() installed before NewRaft: protocol time is fully controlled; only TimeController.Advance progresses it. Focused tests cover no-auto-progress, Advance-driven election, step boundaries/order/single-fire, re-armed timers, Register, and the new TestTimeControllerSkipsPausedAndStoppedNodes (paused node receives no steps across Advance(500); held timers drive the election after Resume; Advance after Stop discards stale timers without hanging).

**缓存实例引用**

One shared virtualClock per TimeController, created in NewTimeController and referenced by every node whose Config.Clock was set to tc.Clock(); the reference is stable for the controller's lifetime. Each node's runtime additionally holds a nodeClock wrapper bound to that node (fresh wrapper per NewRaft), so restart re-attribution happens automatically.

**目标绑定方式**

Not a message-target capability: NewRaft binds the shared virtual clock to the node by wrapping it in a nodeClock that holds the concrete *Raft; Advance reads that binding (paused flag and RaftState) directly, so exclusion works for every node wired through Config.Clock without registry lookups and survives LifecycleController.Restart.

**缓存变化与失败语义**

No message cache. Advance moves the shared clock; at each boundary due timers are classified: running-node timers fire once, paused-node timers are held (fired on a later Advance after Resume), stopped/crashed-runtime timers are discarded. Unattributed timers armed directly on the shared clock always fire. Pending/Inject/Drop/Clear/observation/external input never advance time.

**仍未覆盖**

- inmem_transport_delivery_timeouts (inmem_transport.go) and controlled_transport/message_controller wrapper timeouts remain wall-clock based: they are RPC delivery deadlines, not protocol timers; they never gate protocol state transitions and in loopback tests complete immediately, so virtualization would require changing transport construction without protocol benefit
- caller_side_deadlines (Apply/AddVoter/etc. timeouts, requestConfigChange) stay real per the capability spec (caller-side deadlines excluded)
- metrics_and_logging_timestamps (dispatchLogs MeasureSince sites, emitLogStoreMetrics, Log.AppendedAt) stay real per spec (metrics only)
- per_node_step_skipping: exclusion is enforced at timer delivery and by the pause gates rather than by freezing each node's view of the shared clock; stopped/crashed nodes have no live protocol goroutines and their stale timers are discarded, and per-node drift/advancement is out of v0 scope

**调用示例**

```go
// Requires: conf *raft.Config (LocalID set), fsm raft.FSM, store *raft.InmemStore, snaps *raft.InmemSnapshotStore, trans *raft.InmemTransport
tc := raft.NewTimeController(10 * time.Millisecond) // one Advance step = 10ms
conf.Clock = tc.Clock()                             // wire before NewRaft
r, err := raft.NewRaft(conf, fsm, store, store, snaps, trans)
if err != nil { /* handle */ }
if err := tc.Advance(25); err != nil { /* handle */ } // fire due heartbeat/election timers
state := r.State() // Leader once Advance has driven the election
```

```go
// Requires: confs []*raft.Config, fsms []raft.FSM, stores []*raft.InmemStore, snaps []*raft.InmemSnapshotStore, trans []*raft.InmemTransport
tc := raft.NewTimeController(time.Millisecond) // every node shares one virtual clock
for i := range confs {
    confs[i].Clock = tc.Clock() // complete control before any goroutine starts
}
// ... raft.NewRaft(confs[i], ...) for each node, then optionally tc.Register(node) ...
if err := tc.Advance(100); err != nil { /* handle */ } // advance all running nodes together
```

### 随机性控制

**本次生成入口**

- `NewRandomController`
- `RandomController.Choices`

**启用与使用范围**

In-package focused tests only: TestRandomControllerDeterminism (same seed and draw order reproduce identical sequences, jitter and values stay inside the legal domain, repeated decisions vary, Choices returns deep copies) and TestRandomControllerNodeDraws (a Config-installed controller on a real NewRaft node records follower heartbeat and snapshot draws with the correct Owner, stable names, and in-domain values).

**缓存实例引用**

One controller per node: the consumer creates it with NewRandomController(seed, ServerID) and installs it via Config.Random; NewRaft binds it to the node's unexported Raft.random field before goroutine launch, and every draw of that node routes through that same instance for the node's lifetime. A restart (fresh NewRaft with the same Config.Random) re-binds the same controller instance and its history, so the reference is stable and reusable across lifecycle changes.

**目标绑定方式**

Not a message-target capability; ownership binding is explicit and concrete instead. Each controller is constructed for one target-native owner (ServerID) and every recorded RandomChoice carries that Owner field; the node hook resolves its own controller from the Raft instance bound at construction, so a choice is always unambiguously attributable to its node.

**缓存变化与失败语义**

Every protocol draw appends one RandomChoice to the ordered history and advances the deterministic source; Choices() is side-effect-free; there is no eviction, Drop, or Clear, and the history only grows. Repeated decisions always consume the next value from the same source, so values keep varying (verified by test); a new controller with a new seed starts a fresh empty history. Installation itself records nothing.

**调用示例**

```go
// Requires: seed int64; nodeID raft.ServerID; fsm raft.FSM; logs raft.LogStore; stable raft.StableStore; snaps raft.SnapshotStore; trans raft.Transport
rc := raft.NewRandomController(seed, nodeID)
conf := raft.DefaultConfig()
conf.LocalID = nodeID
conf.Random = rc
r, err := raft.NewRaft(conf, fsm, logs, stable, snaps, trans)
if err != nil { return err }
```

```go
// Requires: rc *raft.RandomController
choices := rc.Choices()
for _, c := range choices {
    if c.Name == raft.RandomChoiceElectionTimeout && c.Owner == raft.ServerID("node1") {
        _ = c.Value // selected election timeout in [conf.ElectionTimeout, 2*conf.ElectionTimeout)
    }
}
```

```go
// Requires: seed int64; nodeID raft.ServerID
rc1 := raft.NewRandomController(seed, nodeID)
rc2 := raft.NewRandomController(seed, nodeID)
// The same draw order (identical protocol runs) on rc1 and rc2 yields identical Choices().
```

### 生命周期控制

**目标已有入口**

- `Raft.Shutdown`
- `NewRaft`

**本次生成入口**

- `NewLifecycleController`
- `LifecycleController.Pause`
- `LifecycleController.Resume`
- `LifecycleController.Stop`
- `LifecycleController.Crash`
- `LifecycleController.Restart`
- `LifecycleController.Register`
- `LifecycleController.Raft`
- `LifecycleController.Status`
- `ErrLifecycleUnsupported`
- `LifecycleStatus`

**启用与使用范围**

Focused tests in lifecycle_control_test.go: pause blocks protocol progress (single node stays Follower with commit index 0 while paused and reaches Leader after Resume), pause blocks Apply on a leader until Resume, pause stops protocol output (a paused leader stops heartbeats so the follower starts an election), pause blocks inbound message handling (a paused follower does not process injected AppendEntries - commit index does not advance and the leader's Apply does not complete - and recovers after Resume), Stop+Restart yields a fresh runtime that re-elects itself while the old runtime stays Shutdown, Crash+Restart preserves term and durable log, Crash completes while a leadership transfer is in flight in a controlled deployment and the captured TimeoutNow entry survives, Restart keeps a pre-crash pending message injectable through the re-bound fresh wrapper (TestLifecycleControllerRestartKeepsPendingInjectible), error paths and register-replace semantics (including nil-node and no-stored-config errors), ErrLifecycleUnsupported errors.Is classification, and a 3-node Stop/Restart/rejoin test with transport re-Connect. Cross-capability: TestTimeControllerSkipsPausedAndStoppedNodes verifies the clock-level step exclusion; TestMessageControllerDropAndInjectPreserveOrder and TestMessageControllerClosedOwnerRebind verify the order-preserving cache and re-bound ownership the lifecycle interaction relies on.

**缓存实例引用**

One registry entry per concrete ServerID; entries remain stable across lifecycle operations; the runtime binding is replaced on Restart and nil after Stop/Crash.

**目标绑定方式**

Restart resolves the registered ServerID entry and validates its recorded status (stopped or crashed) before rebuilding; the fresh runtime is bound to the same identity, configuration, and durable stores through NewRaft (the target's normal recovery constructor), the old runtime binding is replaced, and in controlled deployments a fresh ControlledTransport wrapper over the same underlying transport and MessageController is created with every pending entry re-bound to it.

**缓存变化与失败语义**

Node registry keyed by ServerID: Register binds or replaces an entry; Stop and Crash discard the runtime binding (Raft(id) returns nil) while retaining construction parameters; Restart re-binds the fresh runtime and re-binds pending MessageController entries owned by the old wrapper to the fresh wrapper; Status records the lifecycle state; Pause/Resume flip the recorded status without touching the binding; all operations on unknown IDs return errors and leave the registry unchanged; pending MessageController entries are never cleared or reordered by lifecycle operations.

**仍未覆盖**

- strict_crash_context_bounded: Crash while a leadership transfer is in flight waits for the auxGo-tracked transfer goroutines; the transfer goroutine can remain blocked in the TimeoutNow transport call until the transport-level timeout resolves (ControlledTransport uses 10x the base timeout for TimeoutNow/InstallSnapshot), so Crash is bounded by that timeout rather than instantaneous; the goroutine never mutates durable storage or the FSM, and every other blocking point aborts on shutdown signals
- time_controller_registry_restart: TimeController.nodes is bookkeeping-only and is not automatically re-bound by LifecycleController.Restart; a subsequent Register of the fresh runtime returns a duplicate-ID error (verified behavior of TestTimeControllerRegister); Advance is unaffected because it is driven by the shared virtual clock and NewRaft re-wraps Config.Clock with a fresh nodeClock for the fresh runtime
- pause_boundary_ack: Pause waits for the main loop's pause acknowledgment; the replication/FSM/snapshot goroutines reach their gate at their next loop boundary, so an operation already in flight at the time of the Pause call completes first (documented quiescence scope)
- per_node_time_drift: the shared-clock model advances all running nodes together; per-node drift or separate advancement is out of v0 scope (paused, stopped, and crashed nodes are excluded at the clock level instead)

**调用示例**

```go
// Requires: conf *raft.Config (LocalID set), fsm raft.FSM, store *raft.InmemStore, snaps *raft.InmemSnapshotStore, trans *raft.InmemTransport
lc := raft.NewLifecycleController()
r, err := raft.NewRaft(conf, fsm, store, store, snaps, trans)
if err != nil { /* handle */ }
if err := lc.Register(r); err != nil { /* handle */ }
if err := lc.Pause(conf.LocalID); err != nil { /* handle */ }
if err := lc.Resume(conf.LocalID); err != nil { /* handle */ }
if err := lc.Stop(conf.LocalID); err != nil { /* handle */ }
if err := lc.Restart(conf.LocalID); err != nil { /* handle */ }
r2 := lc.Raft(conf.LocalID)
if r2 == nil { /* restart failed or node unknown */ }
if err := lc.Crash(conf.LocalID); err != nil { /* handle */ }
if err := lc.Restart(conf.LocalID); err != nil { /* handle */ }
st, err := lc.Status(conf.LocalID)
if err == nil && st == raft.LifecycleRunning { /* fresh runtime is bound and running */ }
```

```go
// Requires: leader *raft.Raft, followerID raft.ServerID, lc *raft.LifecycleController, transLeader *raft.InmemTransport, transFollower *raft.InmemTransport
if err := lc.Stop(followerID); err != nil { /* handle */ }
if err := lc.Restart(followerID); err != nil { /* handle */ }
transLeader.Connect(transFollower.LocalAddr(), transFollower) // restore in-memory routes wiped by shutdown
transFollower.Connect(transLeader.LocalAddr(), transLeader)
```

### 状态观察

**目标已有入口**

- `Raft.State`
- `Raft.Stats`
- `Raft.LeaderWithID`
- `Raft.LastContact`
- `Raft.CurrentTerm`
- `Raft.LastIndex`
- `Raft.CommitIndex`
- `Raft.AppliedIndex`
- `Raft.GetConfiguration`
- `Raft.LeaderCh`
- `Raft.RegisterObserver`
- `Raft.DeregisterObserver`
- `Observer.GetNumObserved`
- `Observer.GetNumDropped`

**调用示例**

```go
// Requires: r *raft.Raft
state := r.State() // Follower | Candidate | Leader | Shutdown
leaderAddr, leaderID := r.LeaderWithID()
stats := r.Stats() // map[string]string
cf := r.GetConfiguration()
if err := cf.Error(); err == nil { cfg := cf.Configuration() }
```

### 外部输入

**目标已有入口**

- `Raft.Apply`
- `Raft.ApplyLog`
- `Raft.AddVoter`
- `Raft.AddNonvoter`
- `Raft.RemoveServer`
- `Raft.DemoteVoter`

**调用示例**

```go
// Requires: r *raft.Raft (leader)
future := r.Apply([]byte("set x 1"), 5*time.Second)
if err := future.Error(); err != nil { /* ErrNotLeader, ErrLeadershipLost, ErrEnqueueTimeout */ }
idx := future.Index()
resp := future.Response()
```

```go
// Requires: r *raft.Raft (leader)
f := r.AddVoter("node2", "10.0.0.2:8300", 0, 5*time.Second)
if err := f.Error(); err != nil { /* ErrNotLeader, ErrLeadershipLost */ }
logIndex := f.Index()
```

## Reviewer 最终结论

- 总体结论：`PASS`
- 非阻塞剩余风险：
  - Concurrent Drop or Clear during an already-in-flight Inject is not serialized against delivery: the injecting flag guards Inject-vs-Inject, but Drop/Clear remove the entry without checking injecting, so a message whose delivery has begun can still be enqueued after it was concurrently removed. This does not corrupt cache state or reorder entries, but the 'remove without delivering' guarantee is best-effort under that specific race.
  - The awaitResponse goroutine launched after a request is accepted can linger if the target node stops/crashes without responding while the source transport remains open; it only exits on the source transport close. This has no protocol impact and only affects controller bookkeeping.
  - Pause acknowledgment is sent by any gated loop (main, replication, FSM, snapshot), so Pause's quiescence guarantee is best-effort: work already in flight can still complete at the pause boundary, as documented.
  - Wall-clock timeouts remain in ControlledTransport.waitRPC, the controlled pipeline, and Inject's enqueue; these are RPC delivery deadlines, not protocol timers, and are disclosed as outside the time-control scope.
  - TimeController.Register is bookkeeping-only and is not automatically re-bound by LifecycleController.Restart (Advance is clock-driven and the fresh runtime inherits Config.Clock); a re-register after restart returns a duplicate-ID error.
