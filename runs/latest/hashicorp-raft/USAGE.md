# hashicorp-raft 测试接口清单

本文件面向测试接口使用者，只回答有哪些入口、如何使用以及哪些路径仍有限制。
详细分类、源码证据、修改方式和审查过程见 `AUDIT.md` 与三份 JSON 报告。

## 快速接口矩阵

| 能力 | 修改前状态 | 目标已有入口 | 本次生成入口 | 当前结论 |
|---|---|---|---|---|
| 消息捕获 | `PATCHABLE` | `Transport (interface: Consumer/AppendEntries/RequestVote/InstallSnapshot/TimeoutNow/SetHeartbeatHandler)`<br>`NewInmemTransport`<br>`InmemTransport.Consumer`<br>等 8 项 | `NewMessageController`<br>`MessageController.Attach`<br>`MessageController.SetControlled`<br>等 10 项 | 已生成接口；覆盖 6 条路径，未覆盖 1 条 |
| 消息注入 | `PATCHABLE` | `Transport (interface)`<br>`InmemTransport.Consumer`<br>`RPC.Respond`<br>等 5 项 | `MessageController.Inject`<br>`ErrMessageNotPending`<br>`ErrTargetUnavailable`<br>等 6 项 | 已生成接口；覆盖 7 条路径，未覆盖 1 条 |
| 时间控制 | `PATCHABLE` | `Config (HeartbeatTimeout, ElectionTimeout, CommitTimeout, LeaderLeaseTimeout, SnapshotInterval)`<br>`DefaultConfig`<br>`NewRaft`<br>等 4 项 | `TimeController`<br>`NewTimeController`<br>`TimeController.Advance`<br>等 4 项 | 已生成接口；覆盖 14 条路径，未覆盖 4 条 |
| 随机性控制 | `PATCHABLE` | `DefaultConfig`<br>`NewRaft`<br>`Config (HeartbeatTimeout, ElectionTimeout, CommitTimeout, SnapshotInterval)` | `NewRandomController`<br>`RandomController.Choices`<br>`RandomChoice`<br>等 4 项 | 已生成接口；覆盖 2 条路径，未覆盖 3 条 |
| 生命周期控制 | `PATCHABLE` | `Raft.Shutdown`<br>`NewRaft`<br>`WithClose.Close`<br>等 6 项 | `NewLifecycleController`<br>`LifecycleController.Pause`<br>`LifecycleController.Resume`<br>等 9 项 | 已生成接口；覆盖 12 条路径，未覆盖 4 条 |
| 状态观察 | `SUPPORTED` | `Raft.State`<br>`Raft.Stats`<br>`Raft.CurrentTerm`<br>等 13 项 | — | 直接复用目标已有接口 |
| 外部输入 | `SUPPORTED` | `Raft.Apply`<br>`Raft.ApplyLog`<br>`Raft.AddVoter`<br>等 8 项 | — | 直接复用目标已有接口 |

## 消息控制调用顺序

1. 调用报告列出的 NewMessageController 构造器并完成目标接线。
2. 调用 Pending，获得可检查的消息深拷贝快照和稳定 Handle。
3. 测试代码根据目标原生消息字段选择实例；ConsensusSeam 不决定选择策略。
4. 将同一 Handle 交给 Drop 或 Inject；需要全部丢弃时调用 Clear。
5. 根据下方记录的接受点、错误类别和缓存变化决定后续测试动作。

## 接口详情与示例

### 消息捕获

**目标已有入口**

- `Transport (interface: Consumer/AppendEntries/RequestVote/InstallSnapshot/TimeoutNow/SetHeartbeatHandler)`
- `NewInmemTransport`
- `InmemTransport.Consumer`
- `RPC`
- `RPC.Respond`
- `InmemTransport.Connect`
- `InmemTransport.Disconnect`
- `InmemTransport.DisconnectAll`

**本次生成入口**

- `NewMessageController`
- `MessageController.Attach`
- `MessageController.SetControlled`
- `MessageController.Pending`
- `MessageController.Drop`
- `MessageController.Clear`
- `NewCapturingTransport`
- `CapturingTransport.Close`
- `MessageHandle / MessageKind / PendingMessage`
- `ErrMessageNotPending / ErrTargetUnavailable / ErrMessageNotAccepted`

**启用与使用范围**

SetControlled(true) activates capture on all attached transports; every in-boundary request and its eventual response are then retained as pending entries until Drop, Clear, or Inject.

**缓存实例引用**

Enumeration returns a PendingMessage whose Handle is the concrete cache instance: an unexported monotonic uint64, stable while pending, invalid (ErrMessageNotPending) after Drop, Clear, or successful Inject, and never reused.

**目标绑定方式**

Each request's Target is the ServerID of the receiving decorator (t.localID); Inject resolves it through the controller's transport map to the CapturingTransport whose consumer channel is that node's rpcCh consumed by Raft.processRPC. A decorator whose doneCh is closed (node shut down) is treated as unavailable; the injected RPC carries the controller-owned command, the swapped response channel, and the replayable reader.

**缓存变化与失败语义**

Capture appends one entry per concrete target in acceptance order. Drop and Clear remove entries, close their watcher signal, release stream buffers, and invalidate handles without reordering the remaining entries. Successful Inject removes the entry and invalidates its handle; a later protocol failure never restores it. Invalid handle (ErrMessageNotPending), unavailable target (ErrTargetUnavailable), or explicit non-acceptance (ErrMessageNotAccepted) preserve the entry.

**仍未覆盖**

- heartbeat fast-path for transports implementing SetHeartbeatHandler: NetworkTransport/TCP sockets are outside the system boundary; the decorator delegates SetHeartbeatHandler and the in-boundary InmemTransport ignores it, so in-boundary capture is complete.

**调用示例**

```go
// Requires: rawA, rawB *raft.InmemTransport; addrA, addrB raft.ServerAddress; conf *raft.Config; fsm raft.FSM; store *raft.InmemStore; snaps raft.SnapshotStore
rawA.Connect(addrB, rawB)
rawB.Connect(addrA, rawA)
controller := raft.NewMessageController()
capA := raft.NewCapturingTransport(rawA, raft.ServerID("node-a"))
capB := raft.NewCapturingTransport(rawB, raft.ServerID("node-b"))
controller.Attach(capA)
controller.Attach(capB)
nodeA, err := raft.NewRaft(conf, fsm, store, store, snaps, capA)
nodeB, err := raft.NewRaft(conf, fsm, store, store, snaps, capB)
controller.SetControlled(true)
for _, pm := range controller.Pending() {
	if pm.Kind == raft.MessageKindAppendEntries && pm.Target == raft.ServerID("node-b") {
		if ae, ok := pm.Message.(*raft.AppendEntriesRequest); ok && len(ae.Entries) > 0 {
			_ = controller.Inject(pm.Handle)
			break
		}
	}
}
```

### 消息注入

**目标已有入口**

- `Transport (interface)`
- `InmemTransport.Consumer`
- `RPC.Respond`
- `InmemTransport.Connect`
- `InmemTransport.Disconnect`

**本次生成入口**

- `MessageController.Inject`
- `ErrMessageNotPending`
- `ErrTargetUnavailable`
- `ErrMessageNotAccepted`
- `NewMessageController / MessageController.Attach`
- `NewCapturingTransport`

**启用与使用范围**

Controlled mode: entries retained by SetControlled(true) are injected one at a time through the normal ingress; the test schedules messages and handles selection policy.

**缓存实例引用**

The injected handle identifies the concrete cache instance (unexported monotonic uint64); it is stable while pending and becomes invalid (ErrMessageNotPending) immediately upon successful injection.

**目标绑定方式**

Entry.Target (ServerID) is resolved through the controller's transport map to the CapturingTransport whose consumer channel is that node's rpcCh; a decorator whose doneCh is closed is unavailable (ErrTargetUnavailable). Request entries are delivered with the controller-owned command, swapped response channel, and replayable reader; response entries are delivered into the preserved original response channel.

**缓存变化与失败语义**

Confirmed acceptance removes the entry and invalidates the handle; later protocol failure never restores it (no duplicate delivery). ErrMessageNotPending, ErrTargetUnavailable, and ErrMessageNotAccepted all preserve the entry and its handle; Drop/Clear of other entries and acceptance order are unaffected.

**仍未覆盖**

- heartbeat fast-path for transports implementing SetHeartbeatHandler: NetworkTransport/TCP sockets are outside the system boundary; the decorator delegates SetHeartbeatHandler and the in-boundary InmemTransport ignores it, so injection for in-boundary heartbeats flows through the captured AppendEntries path.

**调用示例**

```go
// Requires: controller *raft.MessageController; handle raft.MessageHandle (from controller.Pending())
if err := controller.Inject(handle); err != nil {
	switch {
	case errors.Is(err, raft.ErrMessageNotPending):
	case errors.Is(err, raft.ErrTargetUnavailable):
	case errors.Is(err, raft.ErrMessageNotAccepted):
	}
}
```

```go
// Requires: controller *raft.MessageController; nodeB *raft.Raft; f raft.ApplyFuture
controller.SetControlled(true)
f = nodeB.Apply([]byte("cmd"), 0) // captured before delivery; sender blocks on its transport response channel
var req raft.MessageHandle
for _, pm := range controller.Pending() {
	if pm.Kind == raft.MessageKindAppendEntries && pm.Target == raft.ServerID("node-b") {
		if ae, ok := pm.Message.(*raft.AppendEntriesRequest); ok && len(ae.Entries) > 0 {
			req = pm.Handle
		}
	}
}
_ = controller.Inject(req)
var resp raft.MessageHandle
for _, pm := range controller.Pending() {
	if pm.Kind == raft.MessageKindAppendEntriesResponse && pm.Source == raft.ServerID("node-b") {
		resp = pm.Handle
	}
}
_ = controller.Inject(resp) // original caller completes; commit proceeds
```

### 时间控制

**目标已有入口**

- `Config (HeartbeatTimeout, ElectionTimeout, CommitTimeout, LeaderLeaseTimeout, SnapshotInterval)`
- `DefaultConfig`
- `NewRaft`
- `ValidateConfig`

**本次生成入口**

- `TimeController`
- `NewTimeController`
- `TimeController.Advance`
- `Config.TimeController`

**启用与使用范围**

Focused in-package tests in time_controller_test.go: TestTimeControllerUnit (five subtests covering no-progress, per-step due-timer delivery, Advance(n) boundaries including re-armed timers, detached-subject exclusion, transport timeout hook), TestTimeControllerNodeWiring (NewRaft attach before startup plus Shutdown detach), and TestTimeControllerAdvanceReactiveReArming (regression: synthetic re-arming consumer asserts one Advance(2) yields two deliveries and the next step yields a third; follower heartbeat subtest asserts re-arm draws are recorded before Advance returns on a real skipStartup node's runFollower loop).

**缓存实例引用**

One TimeController instance owns one shared virtual clock; subjects are attached by *Raft pointer when Config.TimeController is set before NewRaft and remain attached until Shutdown detaches them, so the controller reference is stable for each node's lifetime; pause/resume (LifecycleController) temporarily removes a subject from the running set while keeping its timers.

**目标绑定方式**

Subjects are attached by *Raft pointer identity: NewRaft calls TimeController.attach(r) before starting goroutines; each virtual timer is attributed to the *Raft that armed it; timers of detached (stopped/crashed) or paused subjects are never delivered as steps; the in-boundary InmemTransport is located by unwrapping CapturingTransport decorators (controlledInmemTransport) and wired with afterFor(r) so transport timeouts share the node's clock.

**仍未覆盖**

- caller-provided deadlines (Apply/Barrier/Restore timeouts and requestConfigChange) intentionally remain on the real clock; they are caller-facing deadlines excluded by the capability contract, not protocol time
- metrics-only time reads (dispatchLog AppendedAt stamping, MeasureSince/appendStats, emitLogStoreMetrics log age) remain on the real clock; they are informational and do not feed protocol behavior
- out-of-boundary NetworkTransport/TCP socket timeouts remain real; socket behavior is outside the declared protocol plane and controlledInmemTransport returns nil for it
- strictly synchronous visibility: if a rearmable consumer is descheduled when the bounded settle budget expires, its replacement timer is registered when it next runs (deadline against the then-current virtual time); this is the same boundary a separate Advance(1) call would expose to a descheduled consumer and is documented in the controller doc comment

**调用示例**

```go
// Requires: tc := raft.NewTimeController(time.Millisecond)
// Requires: conf := raft.DefaultConfig(); conf.TimeController = tc
// Requires: fsm raft.FSM, logs raft.LogStore, stable raft.StableStore, snaps raft.SnapshotStore, trans raft.Transport
node, err := raft.NewRaft(conf, fsm, logs, stable, snaps, trans)
if err != nil { return err }
// Protocol time advances only through Advance; each step is a separate boundary
// including timers re-armed in reaction to earlier steps.
if err := tc.Advance(10); err != nil { return err }
_ = node.State()
```

```go
// Requires: tc *raft.TimeController; ch <-chan time.Time armed by a controlled node's protocol timer
tc.Advance(2) // equivalent to two separate Advance(1) calls: the timer's re-arm after the
              // first delivery is registered before the second step advances the clock
```

### 随机性控制

**目标已有入口**

- `DefaultConfig`
- `NewRaft`
- `Config (HeartbeatTimeout, ElectionTimeout, CommitTimeout, SnapshotInterval)`

**本次生成入口**

- `NewRandomController`
- `RandomController.Choices`
- `RandomChoice`
- `Config.RandomController`

**仍未覆盖**

- generateUUID (util.go:59) uses crypto/rand and is excluded by scope (cryptography, peripheral identifiers)
- fuzzy/ and raft-compat/ subdirectories' own random staggering: separate Go modules outside system_boundary
- non-random scheduling waits (time.After for backoff, caller-supplied Apply/Barrier/Restore deadlines) are not random choices

**调用示例**

```go
// Requires: conf *raft.Config with conf.LocalID set, fsm raft.FSM, logs raft.LogStore, stable raft.StableStore, snaps raft.SnapshotStore, trans raft.Transport
rc := raft.NewRandomController(42) // same seed + draw order reproduce the sequence
conf.RandomController = rc         // install before NewRaft: no uncontrolled draw
node, err := raft.NewRaft(conf, fsm, logs, stable, snaps, trans)
if err != nil { /* handle */ }
// later, from the test goroutine (never advances time, no side effects):
choices := rc.Choices() // []raft.RandomChoice
for _, ch := range choices {
    _ = ch.Owner // raft.ServerID of the node that drew
    _ = ch.Name  // "heartbeat" | "election" | "commit" | "heartbeat_interval" | "snapshot"
    _ = ch.Value // selected extra duration in [0, base)
}
```

```go
// Requires: confA, confB *raft.Config with distinct LocalIDs (aggregated controller)
rc := raft.NewRandomController(7, confA.LocalID, confB.LocalID)
confA.RandomController = rc
confB.RandomController = rc
nodeA, errA := raft.NewRaft(confA, fsmA, logsA, stableA, snapsA, transA)
nodeB, errB := raft.NewRaft(confB, fsmB, logsB, stableB, snapsB, transB)
// every recorded choice carries the concrete ServerID that made it
```

### 生命周期控制

**目标已有入口**

- `Raft.Shutdown`
- `NewRaft`
- `WithClose.Close`
- `WithPeers.Connect`
- `WithPeers.Disconnect`
- `Raft.State`

**本次生成入口**

- `NewLifecycleController`
- `LifecycleController.Pause`
- `LifecycleController.Resume`
- `LifecycleController.Stop`
- `LifecycleController.Crash`
- `LifecycleController.Restart`
- `LifecycleController.Node`
- `ErrLifecycleUnsupported`
- `RestartFunc`

**启用与使用范围**

Package-local tests (lifecycle_controller_test.go) exercise the controller through its public methods on real NewRaft nodes: Stop/Restart, Crash/Restart, Stop-while-paused, invalid transitions, untracked subjects, pause-gate blocking and shutdown unblocking, an event-received-after-Pause regression, and the crash-boundary regression TestLifecycleController_CrashWaitsForLeadershipTransfer which drives a real leadership transfer to a dead peer and asserts that after Crash returns the transfer-in-progress flag is cleared and the transfer future is resolved.

**缓存实例引用**

The controlled subject is tracked as *Raft pointer identity; it is stable across Pause/Resume/Stop/Crash and is replaced only by a successful Restart, after which Node() returns the fresh runtime.

**目标绑定方式**

Each LifecycleController owns exactly one *Raft subject; every method validates target == controller.Node() by pointer identity and checks the recorded lifecycle phase before acting; Restart additionally validates that the fresh subject keeps the same LocalID.

**缓存变化与失败语义**

No message cache is owned by the LifecycleController. Pending MessageController entries are controller-owned and survive lifecycle changes; Inject to a stopped/crashed target fails with ErrTargetUnavailable and preserves the entry (existing message-controller behavior).

**仍未覆盖**

- Strict zero-latency pause: an event already received and past its post-receive gate check at the moment Pause sets the paused flag may complete its handling concurrently with Pause returning; every event received afterwards is held until Resume (inherent linearization point of a Go select-based loop; documented in the controller doc comment)
- The leaderLoop group-commit drain (GROUP_COMMIT_LOOP nested select) runs inside a case body that already passed its post-receive gate; applies drained there after Pause returns complete as part of the already-started handler (same linearization point)
- Informational telemetry (emitLogStoreMetrics goroutine) and in-flight transport RPC waits are not gated while paused (outside the protocol plane / already in flight at pause time)
- Transport-owned goroutines (inmemPipeline.decodeResponses, snapshot restore monitors) are stopped by pipeline Close / StopAndWait on the stop path, not by the pause gates; they are informational or resolve on transport close

**调用示例**

```go
// Requires: node *raft.Raft, conf *raft.Config, fsm raft.FSM, logs raft.LogStore, stable raft.StableStore, snaps raft.SnapshotStore, trans raft.Transport
stopFuture := node.Shutdown()
if err := stopFuture.Error(); err != nil { /* handle */ }
// Restart over the same durable stores (re-connect transport peers first):
node2, err := raft.NewRaft(conf, fsm, logs, stable, snaps, trans)
```

```go
// Requires: node *raft.Raft (running), conf *raft.Config, fsm raft.FSM,
// logs raft.LogStore, stable raft.StableStore, snaps raft.SnapshotStore
lc := raft.NewLifecycleController(node, func() (*raft.Raft, error) {
	trans := raft.NewInmemTransport(raft.ServerAddress("node-1"))
	return raft.NewRaft(conf, fsm, logs, stable, snaps, trans)
})
if err := lc.Pause(node); err != nil { /* handle; Pause/Resume are core_hook */ }
if err := lc.Resume(node); err != nil { /* handle */ }
if err := lc.Stop(node); err != nil { /* handle */ }
if err := lc.Restart(node); err != nil { /* handle */ }
node2 := lc.Node() // fresh runtime with the same LocalID
```

```go
// Requires: node *raft.Raft, lc *raft.LifecycleController (wired as above)
if err := lc.Crash(node); err != nil { /* handle */ }
if err := lc.Restart(node); err != nil { /* handle */ }
node2 := lc.Node() // fresh runtime recovering pre-crash durable state
```

```go
// Requires: err error returned by a LifecycleController method
if errors.Is(err, raft.ErrLifecycleUnsupported) {
	// operation cannot be implemented without core semantic changes
}
```

### 状态观察

**目标已有入口**

- `Raft.State`
- `Raft.Stats`
- `Raft.CurrentTerm`
- `Raft.CommitIndex`
- `Raft.AppliedIndex`
- `Raft.LastIndex`
- `Raft.LeaderWithID`
- `Raft.LastContact`
- `Raft.GetConfiguration`
- `Raft.RegisterObserver`
- `Raft.DeregisterObserver`
- `Observer`
- `InmemStore.GetLog`

**调用示例**

```go
// Requires: node *raft.Raft
state := node.State()          // raft.Follower|Candidate|Leader|Shutdown
term := node.CurrentTerm()
commit := node.CommitIndex()
applied := node.AppliedIndex()
stats := node.Stats()         // map[string]string, fresh copy
```

```go
// Requires: node *raft.Raft
cf := node.GetConfiguration()
if err := cf.Error(); err == nil {
    cfg := cf.Configuration() // raft.Configuration{Servers []raft.Server}
    idx := cf.Index()
}
```

### 外部输入

**目标已有入口**

- `Raft.Apply`
- `Raft.ApplyLog`
- `Raft.AddVoter`
- `Raft.AddNonvoter`
- `Raft.RemoveServer`
- `Raft.DemoteVoter`
- `Raft.AddPeer`
- `Raft.RemovePeer`

**调用示例**

```go
// Requires: node *raft.Raft (current leader)
f := node.Apply([]byte("set:key=val"), 0)
if err := f.Error(); err != nil { /* ErrNotLeader | ErrEnqueueTimeout | ErrLeadershipLost */ }
idx := f.Index() // after Error() returns nil
resp := f.Response() // FSM.Apply return value; check for FSM errors
```

```go
// Requires: node *raft.Raft (current leader), id raft.ServerID, addr raft.ServerAddress
cf := node.AddVoter(id, addr, 0, 0)
if err := cf.Error(); err != nil { /* ErrNotLeader | ErrLeadershipTransferInProgress | ... */ }
newIndex := cf.Index()
```

## Reviewer 最终结论

- 总体结论：`PASS`
- 非阻塞剩余风险：
  - Crash and Stop converge to the same underlying mechanism (both call Raft.Shutdown + shutdownFuture.Error). This is a target-specific reality: Raft.Shutdown is documented as 'not a graceful operation' and Raft persists term/vote/log eagerly, so there is no shutdown-time protocol-state flush and no distinct durable-state difference between the two; the controller records the phase (stopped vs crashed) only for transition validation. Consumers that require observably different durable state after Stop versus Crash will not get it from this target.
  - MessageController.Clear() does not cancel response-watcher goroutines for requests that were already successfully injected (those requests have left c.entries, so Clear cannot close their droppedCh). If a response to such an in-flight request arrives after Clear, it is recorded into the now-cleared cache, and the watcher goroutine can persist until the decorator is closed. This is a resource/late-capture nuance rather than a lost-entry violation, since the response was not yet pending at Clear time.
  - TimeController.Advance's settle uses a bounded runtime.Gosched budget (512 iterations) to wait for rearmable timers to re-arm between steps. A consumer that is genuinely blocked (for example inside a transport RPC whose virtual timeout is due at a later step) is not re-armed until it unblocks; this matches the boundary a sequence of separate Advance(1) calls would expose to a descheduled consumer, but it is a scheduling-heuristic rather than a hard scheduler-independent guarantee.
  - PendingMessage exposes only the Response command for captured responses; the RPCResponse.Error component of an error-only response (where Response is nil) is not visible through Pending(). The private entry retains the error for injection, and normal raft responses carry a non-nil typed response even when an error is set.
  - Pause has a documented linearization point: an event whose receive and post-receive gate check both completed before Pause set the paused flag may finish handling concurrently with Pause returning. Every event received after the flag is set is held at a gate; this is inherent to a select-based Go loop and does not leave the subject active.
  - Crash/Stop can block for up to the in-boundary transport timeout while in-flight RPC waits resolve (TimeoutNow uses 10*i.timeout, up to 5s with default 500ms real-clock timeout) because the leadership-transfer goroutines are now awaited via routinesGroup. This is bounded and preserves the no-abandoned-context guarantee but is not instantaneous under the real clock.
  - CapturingTransport peer wiring requires connecting the raw InmemTransports underneath the decorators (rawA.Connect(addrB, rawB)); the decorator's WithPeers.Connect delegates to the wrapped transport and will panic if handed another decorator, so callers must follow the documented raw-connect pattern.
