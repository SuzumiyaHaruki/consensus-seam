# hashicorp-raft 测试接口审计报告

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
Analyzer 内容描述修改前状态；生成接口和 Reviewer 内容描述候选修改后状态。
机器可读细节以`capability-report.json`、`interface-report.json`、`review-report.json`为准。

## 消息捕获

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Logical cross-node protocol messages inside system_boundary: requests, responses and one-way messages flowing over the Transport abstraction between *Raft nodes (InmemTransport in scope; NetworkTransport/TCP sockets out of scope)
- 修改前测试接口是否完整：否
- 修改前测试支持判断：Only primitives exist: the Transport interface and per-node consumer channels. Nothing retains messages before delivery, there is no response-visible seam (responses bypass Consumer via RPC.RespChan), and the package's cluster harness (MakeCluster) returns the unexported *cluster type, so external consumers cannot use it. A controller and Transport decorator must be written.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- append_entries (incl. heartbeat): leader replicate()/heartbeat()/pipelineReplicate() -> Transport.AppendEntries or AppendEntriesPipeline -> peer consumerCh -> decorator Consumer -> Raft.processRPC -> AppendEntriesResponse via RespChan
- request_vote: candidate electSelf() -> Transport.RequestVote -> peer consumerCh -> processRPC(requestVote) -> RequestVoteResponse via RespChan
- request_prevote: candidate preElectSelf() -> Transport.RequestPreVote -> peer consumerCh -> processRPC(requestPreVote) -> RequestPreVoteResponse via RespChan
- install_snapshot: leader sendLatestSnapshot() -> Transport.InstallSnapshot (+ data stream) -> consumerCh -> processRPC(installSnapshot) -> InstallSnapshotResponse via RespChan
- timeout_now: leader leadershipTransfer() -> Transport.TimeoutNow -> consumerCh -> processRPC(timeoutNow) -> TimeoutNowResponse via RespChan

### Analyzer 建议（修改前）

- Add MessageController (NewMessageController), MessageHandle (struct backed by unexported uint64), PendingMessage{Handle, Source ServerID, Target ServerID, Kind MessageKind, Message <typed carrier>}, Pending() []PendingMessage, Drop(handle) error, Clear() in a new exported package (adapter) or the raft package.
- Add a Transport decorator (e.g., CapturingTransport) implementing Transport + WithPreVote + WithClose + WithPeers, owning the Consumer channel: read RPCs from the wrapped InmemTransport, deep-copy commands (field-wise/msgpack round-trip), buffer RPC.Reader into memory/bytes.Buffer, swap rpc.RespChan with the controller's channel, and record one pending entry per concrete target (broadcast fans out naturally because each per-peer RPC arrives at its own target consumer).
- Add a typed variant carrier (one struct with a field per command type, or an interface with typed accessors) since no common concrete message struct exists; keep Pending copies independent and stream storage released on Drop/Clear/Inject.
- For responses, record a second pending entry with reversed Source/Target and a new MessageHandle when rpc.Respond fires on the swapped channel; on Inject deliver RPCResponse into the preserved original RespChan so the original caller completes normally.

### 目标已有入口

- `Transport (interface: Consumer/AppendEntries/RequestVote/InstallSnapshot/TimeoutNow/SetHeartbeatHandler)`
- `NewInmemTransport`
- `InmemTransport.Consumer`
- `RPC`
- `RPC.Respond`
- `InmemTransport.Connect`
- `InmemTransport.Disconnect`
- `InmemTransport.DisconnectAll`

### 本次生成接口

- 捕获位置：`message_controller.go / CapturingTransport.serve / MessageController.capture：Interception point: the decorator goroutine is the sole consumer of the wrapped transport's Consumer channel; while capture is enabled every in-boundary request is retained before delivery with its source, target, kind, typed content, replayable stream, and response continuation.`
- Pending Store：`message_controller.go / MessageController.entries / order：Thread-safe pending cache keyed by MessageHandle with an acceptance-order slice; never silently evicts; request and response entries coexist with independent handles.`
- 公开入口：`message_controller.go / NewMessageController：Externally callable constructor; starts in pass-through (capture disabled) mode and owns one authoritative pending store.`
- 公开入口：`message_controller.go / MessageController.Attach：Wires a CapturingTransport to the controller under its local ServerID; must run before the node using the transport starts and before capture is enabled.`
- 公开入口：`message_controller.go / MessageController.SetControlled：Enables/disables capture for every attached transport; disabled by default so ordinary production behavior is unchanged.`
- 公开入口：`message_controller.go / MessageController.Pending：Returns fresh deep copies of all pending entries in controller acceptance order; handles stay stable across calls.`
- 公开入口：`message_controller.go / MessageController.Drop：Removes one pending entry and releases its resources; unknown handle returns ErrMessageNotPending; remaining entries keep their relative order.`
- 公开入口：`message_controller.go / MessageController.Clear：Removes all pending entries and invalidates every outstanding handle.`
- 公开入口：`message_controller.go / NewCapturingTransport：Constructs the Transport decorator that is the sole consumer of the wrapped transport's Consumer channel; pass it to NewRaft in place of the raw transport.`
- 公开入口：`message_controller.go / CapturingTransport.Close：Stops the capture goroutine and closes the wrapped transport when it implements WithClose (invoked by Raft.Shutdown).`
- 公开入口：`message_controller.go / MessageHandle / MessageKind / PendingMessage：Fixed public surface: MessageHandle struct backed by an unexported uint64; MessageKind with underlying type string; PendingMessage{Handle, Source ServerID, Target ServerID, Kind, Message WithRPCHeader}.`
- 公开入口：`message_controller.go / ErrMessageNotPending / ErrTargetUnavailable / ErrMessageNotAccepted：Sentinel errors classifiable with errors.Is, returned by Drop/Inject for invalid handle, unavailable target, and explicit non-acceptance.`

### 使用与范围

- 生产路径：Pass-through: with no controller attached, or while capture is disabled (SetControlled(false), the default), the decorator forwards every RPC unchanged (same command, reader, and response channel), so ordinary production behavior is unchanged.
- 测试路径：SetControlled(true) activates capture on all attached transports; every in-boundary request and its eventual response are then retained as pending entries until Drop, Clear, or Inject.
- 缓存实例引用：Enumeration returns a PendingMessage whose Handle is the concrete cache instance: an unexported monotonic uint64, stable while pending, invalid (ErrMessageNotPending) after Drop, Clear, or successful Inject, and never reused.
- 目标绑定方式：Each request's Target is the ServerID of the receiving decorator (t.localID); Inject resolves it through the controller's transport map to the CapturingTransport whose consumer channel is that node's rpcCh consumed by Raft.processRPC. A decorator whose doneCh is closed (node shut down) is treated as unavailable; the injected RPC carries the controller-owned command, the swapped response channel, and the replayable reader.
- 缓存变化与失败语义：Capture appends one entry per concrete target in acceptance order. Drop and Clear remove entries, close their watcher signal, release stream buffers, and invalidate handles without reordering the remaining entries. Successful Inject removes the entry and invalidates its handle; a later protocol failure never restores it. Invalid handle (ErrMessageNotPending), unavailable target (ErrTargetUnavailable), or explicit non-acceptance (ErrMessageNotAccepted) preserve the entry.
- 复制策略：Deep copy at capture (controller-private) and at every Pending call (fresh independent snapshots); byte slices, RPC headers, and nested Log entries copied field-wise; one-shot InstallSnapshot streams buffered into bytes.Reader at capture for independent replay; Pending never exposes routing resources; injection uses only the private controller copy.
- Capture is implemented at the lowest shared typed boundary (Transport.Consumer) via a decorator that owns the consumer channel; one authoritative MessageController is attached to every node's decorator, so no message can bypass the cache or race another consumer while capture is enabled.
- Response capture swaps rpc.RespChan at capture time; the protocol response is recorded with reversed routing and a new handle, and the preserved original channel is only completed when the response entry is injected, preserving synchronous callers, channels, and pipeline futures.
- Deep copies are taken at capture (controller-private) and again at every Pending call; injection always uses the private copy. Byte slices, RPC headers, and nested Log entries are copied field-wise; one-shot InstallSnapshot streams are buffered into a bytes.Reader at capture so every delivery replays independently.
- A copy or stream-buffer failure completes the original exchange with an error through the preserved response channel (observable by the sender) and never forwards a partially consumed or aliased original.
- Drop/Clear of a request entry leaves the original sender to its own transport timeout (InmemTransport command timeout, 500ms real time); the controller never fabricates a response.
- The cache never silently evicts: handles are monotonic unexported uint64 identities, stable while pending, invalid after Drop/Clear/successful Inject, and never reused. All controller state is guarded by one mutex; response watcher goroutines exit on Drop/Clear or decorator Close.
- Message uses the existing common WithRPCHeader interface as the typed native carrier (no bare any); concrete commands are recovered by type switch, e.g. pm.Message.(*raft.AppendEntriesRequest).
- Peer wiring (InmemTransport.Connect) must be done on the raw transports underneath the decorators, because senders route directly into the raw consumer channel of the receiving node; the decorator claims WithPreVote and delegates, which all transports in this module support.

### 已覆盖路径

- append_entries (incl. heartbeat): leader replicate()/heartbeat()/pipelineReplicate() -> Transport.AppendEntries or AppendEntriesPipeline -> peer consumerCh -> CapturingTransport.serve -> controller capture (pending) -> Inject -> Raft.processRPC -> AppendEntriesResponse -> swapped captureCh -> response pending -> Inject response -> original RespChan
- request_vote: candidate electSelf() -> Transport.RequestVote -> peer consumerCh -> decorator capture -> Inject -> processRPC(requestVote) -> RequestVoteResponse -> captured response entry -> Inject response -> original RespChan
- request_prevote: candidate preElectSelf() -> Transport.RequestPreVote -> peer consumerCh -> decorator capture -> Inject -> processRPC(requestPreVote) -> RequestPreVoteResponse -> captured response entry -> Inject response -> original RespChan
- install_snapshot: leader sendLatestSnapshot() -> Transport.InstallSnapshot (+ one-shot data stream) -> decorator buffers stream and captures -> Inject (replayed stream) -> processRPC(installSnapshot) -> InstallSnapshotResponse -> captured response entry -> Inject response -> original RespChan
- timeout_now: leader leadershipTransfer() -> Transport.TimeoutNow -> peer consumerCh -> decorator capture -> Inject -> processRPC(timeoutNow) -> TimeoutNowResponse -> captured response entry -> Inject response -> original RespChan
- response capture: rpc.Respond on the swapped captureCh is recorded as a separate pending entry with a new MessageHandle and reversed Source/Target; the preserved original RespChan completes the synchronous caller, channel, or pipeline future only when the response entry is injected

### 未覆盖路径

- heartbeat fast-path for transports implementing SetHeartbeatHandler: NetworkTransport/TCP sockets are outside the system boundary; the decorator delegates SetHeartbeatHandler and the in-boundary InmemTransport ignores it, so in-boundary capture is complete.

### 实际实现方式

- Transport decorator (wrapper) at the lowest shared typed boundary (Transport.Consumer) owning the consumer channel: sole consumer of the wrapped channel, forwards unchanged in pass-through mode, retains every RPC while capture is enabled
- Response-channel swap (rpc.RespChan replaced with a controller-owned capture channel) so protocol responses are captured as separate entries with reversed routing and a new handle while the preserved original channel keeps the caller/future completion mechanism
- Typed native carrier via the existing common WithRPCHeader interface implemented by every request and response command; concrete types recovered by type switch
- Field-wise deep copy of every native command and nested log entries, and io.ReadAll buffering of one-shot InstallSnapshot streams into bytes.Reader for independent replay
- Sentinel errors classifiable with errors.Is; controller inactive (pure pass-through) by default so production behavior is unchanged

### 修改前已知限制（供对照）

- Heartbeat fast-path: transports implementing SetHeartbeatHandler (NetworkTransport, out of boundary) can bypass Consumer; in-scope InmemTransport ignores SetHeartbeatHandler (inmem_transport.go:74), so in-boundary capture is complete, but the decorator must also intercept SetHeartbeatHandler for out-of-boundary transports.
- Drop of a captured request leaves the original sender blocked on RespChan until the transport timeout ('command timed out', inmem_transport.go:196); under virtual time this timeout must be resolved by the decorator on the Drop path.
- InstallSnapshot requests carry a one-shot stream (RPC.Reader); capture must buffer it into independently replayable storage before delivery and release it when the entry leaves the cache.
- Source/Target identity: ServerID/ServerAddress (configuration.go:59-61); RPCHeader.ID/Addr supply the sender; Target is the receiving node's local identity.

## 消息注入

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Injection through the same in-boundary logical message routes (per-node Transport consumer -> Raft.processRPC -> RPC.Respond), using controller-owned cached entries
- 修改前测试接口是否完整：否
- 修改前测试支持判断：No Inject-like API exists; the underlying primitive is only a channel send into consumerCh. The full fixed surface (Inject(handle MessageHandle) error, ErrMessageNotPending/ErrTargetUnavailable/ErrMessageNotAccepted, cache-update semantics, handle invalidation) must be added.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- append_entries (incl. heartbeat): Inject -> owning node consumer channel -> processRPC(appendEntries) -> AppendEntriesResponse -> original RespChan
- request_vote: Inject -> consumer channel -> processRPC(requestVote) -> RequestVoteResponse -> original RespChan
- request_prevote: Inject -> consumer channel -> processRPC(requestPreVote) -> RequestPreVoteResponse -> original RespChan
- install_snapshot: Inject (with replayed stream) -> consumer channel -> processRPC(installSnapshot) -> InstallSnapshotResponse -> original RespChan
- timeout_now: Inject -> consumer channel -> processRPC(timeoutNow) -> TimeoutNowResponse -> original RespChan

### Analyzer 建议（修改前）

- Add MessageController.Inject(handle MessageHandle) error performing the same-path delivery: for request entries, send the controller-owned RPC into the owning node's consumer channel; for response entries, send RPCResponse into the preserved original RespChan.
- Define ErrMessageNotPending, ErrTargetUnavailable, ErrMessageNotAccepted as sentinel errors usable with errors.Is; on any failure return the error and keep the cache entry and handle intact; on successful send remove the entry and invalidate the handle.
- Wire the controller's per-node decorators so Inject resolves the concrete target node (ServerID) that owns the entry; document that Inject returns after acceptance (enqueue), not after processing, commit, or response.

### 目标已有入口

- `Transport (interface)`
- `InmemTransport.Consumer`
- `RPC.Respond`
- `InmemTransport.Connect`
- `InmemTransport.Disconnect`

### 本次生成接口

- 捕获位置：`message_controller.go / MessageController.Inject：Delivery site: the controller-owned entry is handed to the normal ingress of its real captured target (consumer channel for requests, preserved RespChan for responses); acceptance is the enqueue itself.`
- Pending Store：`message_controller.go / MessageController.entries / order：Same controller-owned pending cache as capture; Inject mutates it only on confirmed acceptance, preserving entries on every classified failure.`
- 公开入口：`message_controller.go / MessageController.Inject：Delivers one pending entry through its normal ingress: a request is enqueued into the target node's consumer channel (Raft.processRPC), a response is sent into the preserved original response channel; confirmed acceptance removes the entry and invalidates the handle.`
- 公开入口：`message_controller.go / ErrMessageNotPending：Classified error (errors.Is) for an invalid/expired handle; the entry is preserved when returned by Inject.`
- 公开入口：`message_controller.go / ErrTargetUnavailable：Classified error (errors.Is) when the captured target is not attached to the controller or its transport is closed; the entry is preserved.`
- 公开入口：`message_controller.go / ErrMessageNotAccepted：Classified error (errors.Is) when the normal ingress explicitly refuses the message (consumer queue full); the entry is preserved.`
- 公开入口：`message_controller.go / NewMessageController / MessageController.Attach：Wiring entrypoints that bind the controller to the CapturingTransport whose consumer channel is the normal ingress for injection.`
- 公开入口：`message_controller.go / NewCapturingTransport：Constructs the decorator that owns the ingress channel used by Inject; must be installed before NewRaft.`

### 使用与范围

- 生产路径：Injection is inert in production defaults: with capture disabled there are no pending entries, Inject returns ErrMessageNotPending, and the decorator forwards every RPC unchanged.
- 测试路径：Controlled mode: entries retained by SetControlled(true) are injected one at a time through the normal ingress; the test schedules messages and handles selection policy.
- 缓存实例引用：The injected handle identifies the concrete cache instance (unexported monotonic uint64); it is stable while pending and becomes invalid (ErrMessageNotPending) immediately upon successful injection.
- 目标绑定方式：Entry.Target (ServerID) is resolved through the controller's transport map to the CapturingTransport whose consumer channel is that node's rpcCh; a decorator whose doneCh is closed is unavailable (ErrTargetUnavailable). Request entries are delivered with the controller-owned command, swapped response channel, and replayable reader; response entries are delivered into the preserved original response channel.
- 缓存变化与失败语义：Confirmed acceptance removes the entry and invalidates the handle; later protocol failure never restores it (no duplicate delivery). ErrMessageNotPending, ErrTargetUnavailable, and ErrMessageNotAccepted all preserve the entry and its handle; Drop/Clear of other entries and acceptance order are unaffected.
- 复制策略：Injection uses only the controller-private copies (capture-time command deep copy, buffered replayable stream, and the private RPCResponse copy recorded by the response watcher); Pending snapshots are never injected and share no state with the delivered message.
- Inject returns as soon as the normal input boundary accepts the message (a buffered channel send); it does not wait for dequeue, processing, state transition, commit, or quiescence, matching queue-acceptance semantics for this asynchronous target.
- The target cannot distinguish acceptance from later protocol failure, so an injected entry is never restored: there is no duplicate delivery risk.
- Request injection uses the same controller-owned instance and end-to-end path as capture (the target decorator's consumer channel, which is exactly the rpcCh consumed by Raft.processRPC); response injection routes into the preserved original RespChan so the synchronous caller, channel, or pipeline future completes normally.
- Target binding resolves the real captured target ServerID through the controller transport map and validates liveness via the decorator's doneCh before sending; identifier arithmetic is not used.
- The decorator consumer channel is buffered (16), matching in-boundary transport buffering; a full queue is the explicit non-acceptance case and preserves the entry.
- Acceptance order and non-injected entries are unaffected by Inject; handles are never reused and injected handles immediately return ErrMessageNotPending.

### 已覆盖路径

- append_entries (incl. heartbeat): Inject -> target decorator consumer channel -> Raft.processRPC(appendEntries) -> AppendEntriesResponse -> captured response entry -> Inject response -> original RespChan
- request_vote: Inject -> consumer channel -> processRPC(requestVote) -> RequestVoteResponse -> captured response entry -> Inject response -> original RespChan
- request_prevote: Inject -> consumer channel -> processRPC(requestPreVote) -> RequestPreVoteResponse -> captured response entry -> Inject response -> original RespChan
- install_snapshot: Inject (with replayed buffered stream) -> consumer channel -> processRPC(installSnapshot) -> InstallSnapshotResponse -> captured response entry -> Inject response -> original RespChan
- timeout_now: Inject -> consumer channel -> processRPC(timeoutNow) -> TimeoutNowResponse -> captured response entry -> Inject response -> original RespChan
- response injection: Inject of a response entry sends the controller-private RPCResponse copy into the preserved original RespChan, completing the synchronous makeRPC caller or inmemPipeline decodeResponses future
- injection error paths: ErrMessageNotPending (unknown or already consumed handle), ErrTargetUnavailable (transport not attached or closed), ErrMessageNotAccepted (consumer queue full) - each preserves the entry and handle

### 未覆盖路径

- heartbeat fast-path for transports implementing SetHeartbeatHandler: NetworkTransport/TCP sockets are outside the system boundary; the decorator delegates SetHeartbeatHandler and the in-boundary InmemTransport ignores it, so injection for in-boundary heartbeats flows through the captured AppendEntries path.

### 实际实现方式

- Same-path injection: the controller-owned RPC (private deep copy, swapped response channel, replayable stream) is enqueued into the target decorator's consumer channel, which is the normal ingress consumed by Raft.processRPC
- Response continuation preserved: response entries deliver the private RPCResponse copy into the preserved original RespChan so synchronous callers, channels, and pipeline futures complete normally
- Classified sentinel errors (ErrMessageNotPending, ErrTargetUnavailable, ErrMessageNotAccepted) classifiable with errors.Is, with entry-preserving semantics on every failure
- Target binding via a ServerID-to-CapturingTransport map with closed-transport (doneCh) detection for unavailable targets
- Acceptance-only completion: non-blocking send into the target ingress; success removes the entry and invalidates the handle, failure preserves both

### 修改前已知限制（供对照）

- Raft's consumer channel is unbuffered (make(chan RPC) at api.go:561 via trans.Consumer()); Inject's send can block until the main loop selects, so acceptance is the send itself - no separate ack exists; this matches 'queue acceptance is sufficient'.
- The target cannot distinguish acceptance from later protocol failure; per contract the controller must not restore an injected entry, so a later failure never duplicates delivery.
- For responses, Inject must route into the swapped-capture channel of the RPC the controller owns (i.e., the entry's stored RespChan), not into the consumer channel.

## 时间控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Protocol time inside system_boundary: election/heartbeat/commit/lease timers in the *Raft state loops and replication goroutines, snapshot-interval timer, and InmemTransport RPC timeouts that feed back into protocol behavior (backoff, step-down)
- 修改前测试接口是否完整：否
- 修改前测试支持判断：There is no clock seam at all: time.After and time.Now are called directly in protocol code, the global math/rand timer staggering cannot be paused, and same-package tests only shorten durations via inmemConfig. An external consumer cannot control protocol time today.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- per-node protocol time: follower heartbeat/election timer (runFollower), candidate election timer (runCandidate), leader lease timer (leaderLoop), replication commit timer and heartbeat interval (replicate/heartbeat/pipelineReplicate), snapshot interval (runSnapshots), InmemTransport RPC timeouts - one shared controller per node, one step = one virtual-time unit advancing every running controlled subject without skipping intermediate due timers

### Analyzer 建议（修改前）

- Introduce package-level hooks (e.g., vars afterFunc(d time.Duration) <-chan time.Time and nowFunc() time.Time defaulting to time.After/time.Now) and route randomTimeout plus every protocol timer site and lastContact/lease read through them (no-op by default => production unchanged).
- Add exported TimeController and NewTimeController(...) wiring every controlled *Raft (and its in-boundary InmemTransport), with Advance(steps uint64) error advancing a shared virtual clock: each step fires all due timers in deadline order and re-arms timers caused by earlier steps; pending/inject/drop/observe/external-input never advance time.
- Document that Advance returns after due events are submitted (timer channels signalled), not after processing, and that paused/stopped/crashed subjects receive no steps; install the controller (or set the hooks) before NewRaft.

### 目标已有入口

- `Config (HeartbeatTimeout, ElectionTimeout, CommitTimeout, LeaderLeaseTimeout, SnapshotInterval)`
- `DefaultConfig`
- `NewRaft`
- `ValidateConfig`

### 本次生成接口

- 公开入口：`time_controller.go / TimeController：System facade for manual protocol-time advancement. Inactive by default: only nodes wired through Config.TimeController use the shared virtual clock; all other protocol time uses the real clock.`
- 公开入口：`time_controller.go / NewTimeController：Constructor NewTimeController(step time.Duration) *TimeController; the virtual clock advances by one positive step per Advance(1) (non-positive steps fall back to 1ms). Construct before NewRaft and assign to Config.TimeController.`
- 公开入口：`time_controller.go / TimeController.Advance：Advance(steps uint64) error advances the shared virtual clock one unit at a time, submits every due timer of attached running subjects in deadline order, and settles the per-step boundary so reactive re-armed timers are registered before the next step; returns after the final boundary closes, not after processing, resulting messages, or state transitions.`
- 公开入口：`config.go / Config.TimeController：Per-node wiring slot. When set before NewRaft, heartbeat/election/commit/heartbeat-interval/leader-lease/snapshot timers, replication backoff waits, last-contact clock reads, and in-boundary InmemTransport RPC timeouts are served from the controller's clock. Nil (production default) leaves every site on the real clock.`

### 使用与范围

- 生产路径：Real clock whenever Config.TimeController is nil: r.timeAfter/r.timeAfterRearmable/r.timeNow delegate to time.After/time.Now, InmemTransport.after delegates to time.After, and randomized timer draws keep the package default. No protocol message, transition condition, persistence, ordering, or recovery behavior changes.
- 测试路径：Focused in-package tests in time_controller_test.go: TestTimeControllerUnit (five subtests covering no-progress, per-step due-timer delivery, Advance(n) boundaries including re-armed timers, detached-subject exclusion, transport timeout hook), TestTimeControllerNodeWiring (NewRaft attach before startup plus Shutdown detach), and TestTimeControllerAdvanceReactiveReArming (regression: synthetic re-arming consumer asserts one Advance(2) yields two deliveries and the next step yields a third; follower heartbeat subtest asserts re-arm draws are recorded before Advance returns on a real skipStartup node's runFollower loop).
- 缓存实例引用：One TimeController instance owns one shared virtual clock; subjects are attached by *Raft pointer when Config.TimeController is set before NewRaft and remain attached until Shutdown detaches them, so the controller reference is stable for each node's lifetime; pause/resume (LifecycleController) temporarily removes a subject from the running set while keeping its timers.
- 目标绑定方式：Subjects are attached by *Raft pointer identity: NewRaft calls TimeController.attach(r) before starting goroutines; each virtual timer is attributed to the *Raft that armed it; timers of detached (stopped/crashed) or paused subjects are never delivered as steps; the in-boundary InmemTransport is located by unwrapping CapturingTransport decorators (controlledInmemTransport) and wired with afterFor(r) so transport timeouts share the node's clock.
- Change scope: core_hook — the production-code changes are default-disabled clock accessors (r.timeAfter/r.timeNow/r.timeAfterRearmable), a named randomized-timeout method (r.randomTimeout), a rearmable periodic-timer flag on the virtual timers, an InmemTransport timeout hook, and NewRaft/Shutdown wiring. No protocol condition, message, transition, persistence, or ordering semantics changed.
- Production defaults preserved: with Config.TimeController nil every site uses time.After/time.Now exactly as before, and with no RandomController the staggering keeps the package default randomTimeout behavior.
- Installation boundary closed for external consumers: NewRaft attaches the controller and wires the InmemTransport hook before any background goroutine starts (api.go:634-639, goFunc startup at 645-647), so no uncontrolled timer can be armed after construction.
- Advance semantics: each step advances every attached running subject one configured unit, delivers only the timers due for that unit in deadline order (stable registration order for equal deadlines), and the settle phase closes the step boundary so a timer re-armed in reaction to an earlier step is registered with its deadline computed against that step's virtual time before the next step advances. Advance(n) therefore behaves as n separate Advance(1) calls and never skips intermediate reactive re-arms.
- Settle is bounded (512 Gosched iterations per step) so a consumer blocked on a later virtual timer, a one-shot consumer that never re-arms, or a detached/paused subject can never stall Advance; if a rearmable consumer has not scheduled before the budget expires, its replacement is registered when it next runs with a deadline against the then-current virtual time, the same observable boundary separate Advance(1) calls would expose to a descheduled consumer.
- Shutdown detaches the subject: protocol timers are discarded and in-flight transport timeout timers are delivered immediately so blocked RPC waits resolve; stopped/crashed subjects receive no steps.
- The same controller can be shared by several nodes (one shared virtual clock, one step advances all attached running subjects), and each timer entry is attributed to its owning *Raft subject.
- Regression coverage: TestTimeControllerAdvanceReactiveReArming contains the synthetic re-arming consumer subtest (one Advance(2) delivers twice with the re-arm registered between steps; a further Advance(1) delivers the third time) and the follower-heartbeat subtest (a one-step heartbeat is delivered per step of a single Advance(n), with re-arm draws recorded through RandomController before Advance returns). Existing TestTimeControllerUnit and TestTimeControllerNodeWiring cover no-progress, per-step delivery, detach and transport hooks.
- Reviewer revision fix: the follower-heartbeat subtest now sets conf.LeaderLeaseTimeout = step (5ms) so it satisfies ValidateConfig (LeaderLeaseTimeout must not exceed HeartbeatTimeout); with that adjustment the focused regression tests pass (go test -run TestTimeControllerAdvanceReactiveReArming and TestTimeControllerUnit|TestTimeControllerNodeWiring both ok), and the whole package compiles (go test -run '^$' ./... ok).

### 已覆盖路径

- external construction route: NewTimeController -> Config.TimeController -> NewRaft attach + transport hook (before goFunc startup at api.go:634-639) -> Advance
- follower heartbeat timer: runFollower -> r.randomTimeout("heartbeat") -> r.timeAfterRearmable
- follower immediate heartbeat on notify: runFollower -> r.timeAfterRearmable(0)
- candidate election timer: runCandidate -> r.randomTimeout("election") -> r.timeAfterRearmable
- leader lease timer and renewal: leaderLoop -> r.timeAfterRearmable(LeaderLeaseTimeout) and r.timeAfterRearmable(checkInterval)
- leadership-transfer election timeout waits: leaderLoop -> r.timeAfter(ElectionTimeout) (one-shot, not rearmable; transfer goroutines tracked via r.goFunc)
- commit timers: replicate/pipelineReplicate -> r.randomTimeout("commit") -> r.timeAfterRearmable
- heartbeat interval: heartbeat -> r.randomTimeout("heartbeat_interval") -> r.timeAfterRearmable
- replication backoff waits: replicateTo/heartbeat -> r.timeAfter(backoff/nextBackoffTime) (one-shot)
- snapshot interval: runSnapshots -> r.randomTimeout("snapshot") -> r.timeAfterRearmable
- last-contact updates and lease contact checks: r.setLastContact -> r.timeNow; checkLeaderLease -> r.timeNow; runFollower heartbeat-failure check -> r.timeNow().Sub(lastContact)
- in-boundary InmemTransport RPC timeouts: makeRPC send/command and inmemPipeline decodeResponses/AppendEntries -> i.after -> TimeController.afterFor(r) (one-shot transport timers)
- shutdown detach: Raft.Shutdown -> TimeController.detach dropping subject timers and resolving in-flight transport timeout timers
- per-step reactive re-arm boundary: Advance(n) settles after each stepOnce, yielding to protocol goroutines until every delivered timer has been received and every rearmable periodic timer re-armed in reaction has been registered, so a single Advance(n) exposes the same boundaries as n separate Advance(1) calls and never skips intermediate reactive re-arms

### 未覆盖路径

- caller-provided deadlines (Apply/Barrier/Restore timeouts and requestConfigChange) intentionally remain on the real clock; they are caller-facing deadlines excluded by the capability contract, not protocol time
- metrics-only time reads (dispatchLog AppendedAt stamping, MeasureSince/appendStats, emitLogStoreMetrics log age) remain on the real clock; they are informational and do not feed protocol behavior
- out-of-boundary NetworkTransport/TCP socket timeouts remain real; socket behavior is outside the declared protocol plane and controlledInmemTransport returns nil for it
- strictly synchronous visibility: if a rearmable consumer is descheduled when the bounded settle budget expires, its replacement timer is registered when it next runs (deadline against the then-current virtual time); this is the same boundary a separate Advance(1) call would expose to a descheduled consumer and is documented in the controller doc comment

### 实际实现方式

- container/heap-based shared virtual clock with deadline-ordered, stable-registration-order timer delivery
- default-disabled protocol clock accessors r.timeAfter/r.timeNow/r.timeAfterRearmable routed through Config.TimeController
- named randomized-timeout method r.randomTimeout so draws stay attributable while the timer is virtualized
- rearmable periodic timer marking: timeTimer.rearmable + TimeController.afterRearmable + Raft.timeAfterRearmable; heartbeat, election, commit, heartbeat-interval, leader-lease and snapshot timers are rearmable; one-shot waits (backoff, transfer timeouts, transport timeouts) are not
- per-step settle: after each stepOnce, Advance records each subject's registration-count snapshot, then yields (runtime.Gosched, bounded at 512 iterations per step) until each delivered timer's channel is drained and each rearmable delivered timer is followed by a new registration for its subject; non-rearmable deliveries settle on drain alone
- InmemTransport RPC timeout hook (setAfter/afterFor) replacing the time.After sites in makeRPC and inmemPipeline
- NewRaft wiring: attach subject and wire the in-boundary transport hook before goroutines start (api.go:634-639); Shutdown detach (api.go:1046)
- leadership-transfer goroutines use r.goFunc and their one-shot ElectionTimeout waits use r.timeAfter, so transfer waits resolve through the same virtual clock and cannot outlive shutdown

### 修改前已知限制（供对照）

- Caller-provided deadlines (Apply/Barrier/Restore timeouts, api.go:831/863/1060) are excluded per contract; requestConfigChange timeout (raft.go:118) is also caller-facing.
- time.Now() reads used for lastContact/leader lease (raft.go:1036-1081, 1956-1960; replication.go:129-133) must also be virtualized or the lease path never fires under a frozen clock.
- emitLogStoreMetrics and snapshot-transfer monitors are informational and excluded, but they also call time.After/time.Since (log.go:180) and would keep running on real time; they do not feed protocol behavior.
- InmemTransport timeouts must be virtualized too; otherwise a captured/held message pair can resolve via real 500ms timeouts and break determinism.

## 随机性控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Hidden non-cryptographic protocol choices inside system_boundary: randomized timeout staggering drawn by randomTimeout in each *Raft node (election, heartbeat, commit, snapshot interval, heartbeat interval)
- 修改前测试接口是否完整：否
- 修改前测试支持判断：No random-control surface exists; math/rand global is package-private behavior. Same-package tests only shorten timeout ranges (inmemConfig, testing.go:24) and cannot fix a seed or observe draws from outside.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- per-node randomized timeout draws: randomTimeout in runFollower (heartbeat), runCandidate (election), replicate/pipelineReplicate (commit), heartbeat (interval), runSnapshots (snapshot interval) - one RandomController per *Raft node

### Analyzer 建议（修改前）

- Add a package-level hook (e.g., var timeoutRand func() int64 defaulting to rand.Int63) used only by randomTimeout; production default unchanged.
- Add exported RandomController with NewRandomController(seed int64, owner ...ServerID), Choices() []RandomChoice returning deep copies of {Name string, Value <typed duration/index>}, recording each draw in order with per-node owner attribution (or one controller per node).
- Install the hook/controller before NewRaft so no uncontrolled draw can occur; same seed and draw order must reproduce the sequence, and repeated decisions draw the next value.

### 目标已有入口

- `DefaultConfig`
- `NewRaft`
- `Config (HeartbeatTimeout, ElectionTimeout, CommitTimeout, SnapshotInterval)`

### 本次生成接口

- 公开入口：`random_controller.go / NewRandomController：Exported constructor: NewRandomController(seed int64, owners ...ServerID) creates a deterministic RandomController seeded with seed; the optional owners list restricts recording to draws made by the listed nodes (empty means record every served draw). Call before NewRaft and assign to Config.RandomController.`
- 公开入口：`random_controller.go / RandomController.Choices：Thread-safe, side-effect-free accessor returning a deep-copied ordered history of recorded random choices (Owner ServerID, Name string, Value time.Duration) in draw order; each call returns an independent snapshot.`
- 公开入口：`random_controller.go / RandomChoice：Recorded choice: Owner is the concrete target-native ServerID of the node that drew, Name is a stable semantic name ("heartbeat", "election", "commit", "heartbeat_interval", "snapshot"), Value is the selected extra duration in [0, base) added to the base timeout.`
- 公开入口：`config.go / Config.RandomController：Pre-start wiring seam: assigning a *RandomController to Config.RandomController routes every randomized protocol timeout draw of that node through the controller; nil (default) keeps the original crypto-seeded math/rand staggering, so production behavior is unchanged.`

### 使用与范围

- change_scope: core_hook - narrow default-disabled seam; no protocol message, transition condition, persistence, ordering, or production-default change (the same rand.Int63() % minVal algorithm and time.After(minVal+extra) are used)
- choice ownership: every recorded RandomChoice carries the concrete target-native Owner ServerID, so an aggregated controller attributes each draw to the node that made it; a per-node controller simply records the same owner throughout
- installation boundary: conf.RandomController must be assigned before NewRaft; NewRaft copies the config and only then starts run/runFSM/runSnapshots, so no uncontrolled draw can occur for an external consumer
- reproducibility: the controller owns a private math/rand source seeded with the constructor seed; same seed and draw order reproduce the sequence, repeated decisions draw the next value rather than reusing a constant; draws by non-listed owners still consume sequence values so the draw order stays reproducible
- visibility: Choices returns the final semantic value (the selected extra duration); the base timeout is configuration input, and random selection is separate from when the timer event fires (time control is a different capability)
- lifecycle: Restart through a fresh NewRaft with the same Config re-wires the fresh subject to the same controller; deterministic control state (rng + history) is controller-owned and survives
- production_mode: with Config.RandomController nil (the default) every timeout draw uses the original global crypto-seeded math/rand path unchanged; a controller is active only when explicitly wired
- test_mode: new random_controller_test.go (package raft) - unit tests for seed reproducibility, legal domain/variation, independent Choices snapshots, owner filtering, plus one end-to-end wiring test (single-node inmem raft with conf.RandomController records heartbeat and election draws attributed to the node)
- copy_strategy: Choices() returns a fresh slice of value-typed RandomChoice elements (ServerID/string/time.Duration), so each snapshot is a deep, independent copy
- cache_effects/capture_boundary/instance_reference/pending_store/target_binding_strategy: not applicable to randomness control

### 已覆盖路径

- per-node randomized timeout draws: randomTimeout in runFollower (heartbeat), runCandidate (election), replicate/pipelineReplicate (commit), heartbeat (interval), runSnapshots (snapshot interval) - one RandomController per *Raft node
- aggregated controller variant: one RandomController wired to several nodes' Config.RandomController, with per-choice Owner attribution via ServerID

### 未覆盖路径

- generateUUID (util.go:59) uses crypto/rand and is excluded by scope (cryptography, peripheral identifiers)
- fuzzy/ and raft-compat/ subdirectories' own random staggering: separate Go modules outside system_boundary
- non-random scheduling waits (time.After for backoff, caller-supplied Apply/Barrier/Restore deadlines) are not random choices

### 实际实现方式

- core_hook: added (*Raft).randomTimeout(name string, minVal time.Duration) which serves the draw through the node's wired RandomController when Config.RandomController is set and otherwise falls back to the unmodified package-level randomTimeout (rand.Int63() % minVal, util.go), keeping production behavior, legal domain, and timeout semantics identical
- dependency injection: new Config.RandomController field (typed, documented, not reloadable at runtime) is copied by NewRaft via r.conf.Store(*conf) before goroutines start (api.go:622-624), so control is installed before the first draw
- new exported surface in package raft: RandomController, RandomChoice, NewRandomController(seed int64, owners ...ServerID), Choices() []RandomChoice, plus the wiring field Config.RandomController
- 9 production call sites in raft.go (5), replication.go (3) and snapshot.go (1) switched from the free function to the per-node method; util.go free function untouched for tests and default path

### 修改前已知限制（供对照）

- generateUUID (util.go:59) uses crypto/rand and is excluded (peripheral identifiers/cryptography).
- The recorded value is the selected timeout duration (semantic), not raw bits; random selection is separate from when the timer event fires (time_control owns firing).
- Only one draw per timer re-arm; there are no other in-scope non-cryptographic choices in the module (fuzzy/ subdirectory is outside the boundary).

## 生命周期控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：The *Raft node runtime and its goroutines (main loop, runFSM, runSnapshots, per-follower replicate/heartbeat/pipeline goroutines) plus consumer-provided durable stores (LogStore/StableStore/SnapshotStore) as the persistence boundary
- 修改前测试接口是否完整：否
- 修改前测试支持判断：Stop and Restart are directly usable (Shutdown + NewRaft), but the five-operation LifecycleController surface (Pause/Resume/Crash/Restart with ErrLifecycleUnsupported classification) does not exist, and Pause/Resume/Crash have no public seam.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- Stop -> Restart: Raft.Shutdown() (waits for goroutines, closes WithClose transport) -> durable stores retain term/log/snapshot/config -> fresh NewRaft with same LocalID, stores, re-connected transport
- Crash -> Restart: core-hook abrupt termination (close shutdownCh without transport close/state flush, resolve in-flight RPC waits, discard *Raft) -> fresh runtime over pre-crash durable state only
- Pause/Resume on same runtime: core-hook pause gates in runFollower/runCandidate/leaderLoop/runFSM/runSnapshots/replicate/heartbeat (no message handling, no time progress, no output; volatile state retained)

### Analyzer 建议（修改前）

- LifecycleController with Pause(target *Raft)/Resume(target)/Stop(target)/Crash(target)/Restart(target) error, NewLifecycleController(...), and ErrLifecycleUnsupported (errors.Is-classifiable).
- Pause/Resume: core_hook - add a per-node paused gate (e.g., pauseCh checked in runFollower/runCandidate/leaderLoop/runFSM/runSnapshots/replicate/heartbeat selects, no-op by default) that retains the same runtime and volatile state while blocking message handling, time steps, and output.
- Stop: facade over Raft.Shutdown() (document transport close and peer re-connect on restart); Restart: facade constructing a fresh *Raft via NewRaft with same LocalID/config/stores (re-Connect InmemTransport peers) - post-stop state after Stop, pre-crash durable state after Crash.
- Crash: core_hook - an abrupt-termination path that closes shutdownCh without transport close or state flush, resolves in-flight RPC waits (disconnect/close in-boundary transport), waits on routinesGroup, and discards the runtime; propose ErrLifecycleUnsupported if any operation cannot be implemented safely instead of fabricating it.
- Ensure pending MessageController entries and deterministic control state (virtual clock, random history) survive lifecycle changes since they are controller-owned, and that fresh subjects are re-wired to all active controllers on Restart.

### 目标已有入口

- `Raft.Shutdown`
- `NewRaft`
- `WithClose.Close`
- `WithPeers.Connect`
- `WithPeers.Disconnect`
- `Raft.State`

### 本次生成接口

- 捕获位置：`lifecycle_controller.go / LifecycleController.Pause / Resume / Stop / Crash / Restart：The lifecycle seam: pause gates in the state loops and replication/snapshot/FSM goroutines (lifecyclePauseGate) plus the target's own stop path (Raft.Shutdown) and normal recovery path (NewRaft through RestartFunc).`
- 公开入口：`lifecycle_controller.go / NewLifecycleController：Externally callable constructor: creates a LifecycleController owning one *Raft node, with a RestartFunc closure that rebuilds the node with the same identity, configuration and durable stores.`
- 公开入口：`lifecycle_controller.go / LifecycleController.Pause：Suspends protocol activity of the running target without stopping it: same runtime and volatile state retained; top-of-loop and post-receive pause gates hold every message, timer and internal event received after Pause sets the paused flag until Resume.`
- 公开入口：`lifecycle_controller.go / LifecycleController.Resume：Continues a paused target on the same runtime; releases the pause gates and re-attaches the node to its TimeController.`
- 公开入口：`lifecycle_controller.go / LifecycleController.Stop：Normal stop via Raft.Shutdown + future.Error(): waits for all goroutines, permits target-defined cleanup (WithClose transport), records the stopped phase for Restart.`
- 公开入口：`lifecycle_controller.go / LifecycleController.Crash：Abrupt termination with no shutdown-time persistence flush (Raft persists term/vote/logs eagerly); discards runtime and volatile state; records the crashed phase for Restart. The goroutine group covers the leadership-transfer contexts, so no stale context survives.`
- 公开入口：`lifecycle_controller.go / LifecycleController.Restart：Rebuilds a fresh *Raft through the supplied RestartFunc (normally NewRaft over the same durable stores) after Stop or Crash; validates the LocalID identity; does not implement protocol catch-up.`
- 公开入口：`lifecycle_controller.go / LifecycleController.Node：Returns the subject currently controlled: the original node, or the fresh runtime created by the most recent Restart.`
- 公开入口：`lifecycle_controller.go / ErrLifecycleUnsupported：Exported sentinel error, classifiable with errors.Is, for an operation that cannot be implemented without core semantic changes.`
- 公开入口：`lifecycle_controller.go / RestartFunc：Constructor-supplied restart wiring type: func() (*Raft, error) rebuilding the controlled subject with the same identity, configuration and durable stores.`

### 使用与范围

- 生产路径：Inactive by default: nodes never attached to a LifecycleController are completely unchanged; pause gates return immediately when the node is not paused, and no controller goroutine or hook runs.
- 测试路径：Package-local tests (lifecycle_controller_test.go) exercise the controller through its public methods on real NewRaft nodes: Stop/Restart, Crash/Restart, Stop-while-paused, invalid transitions, untracked subjects, pause-gate blocking and shutdown unblocking, an event-received-after-Pause regression, and the crash-boundary regression TestLifecycleController_CrashWaitsForLeadershipTransfer which drives a real leadership transfer to a dead peer and asserts that after Crash returns the transfer-in-progress flag is cleared and the transfer future is resolved.
- 缓存实例引用：The controlled subject is tracked as *Raft pointer identity; it is stable across Pause/Resume/Stop/Crash and is replaced only by a successful Restart, after which Node() returns the fresh runtime.
- 目标绑定方式：Each LifecycleController owns exactly one *Raft subject; every method validates target == controller.Node() by pointer identity and checks the recorded lifecycle phase before acting; Restart additionally validates that the fresh subject keeps the same LocalID.
- 缓存变化与失败语义：No message cache is owned by the LifecycleController. Pending MessageController entries are controller-owned and survive lifecycle changes; Inject to a stopped/crashed target fails with ErrTargetUnavailable and preserves the entry (existing message-controller behavior).
- 复制策略：Not applicable to lifecycle control: no cached message or snapshot data is copied; Restart rebuilds a fresh *Raft over the same consumer-supplied durable stores.
- Change scope labels: Pause core_hook, Resume core_hook, Stop facade_only, Crash core_hook (relies on goroutine-group tracking of the leadership-transfer goroutines), Restart facade_only.
- Reviewer conformance issue resolved: the leadership-transfer watcher (raft.go:815) and the leadershipTransfer goroutine (raft.go:873) are registered through r.goFunc, so the target's routinesGroup tracks them and Raft.Shutdown's waitShutdown awaits them. After Crash returns no abandoned execution context can respond to the transfer future or setLeadershipTransferInProgress; the regression test TestLifecycleController_CrashWaitsForLeadershipTransfer proves it with a real transfer to a dead peer.
- Crash and Stop converge in this target: Raft.Shutdown is documented as 'not a graceful operation', Raft persists term, vote and log entries eagerly so no shutdown-time flush exists, and the WithClose transport close only resolves in-flight RPC waits (cleanup, not persistence). The controller records which operation was used (phase stopped vs phase crashed) so Restart reports the correct recovery basis; durable state is identical either way.
- Restart uses the consumer-supplied RestartFunc (normally NewRaft with the same Config, FSM, LogStore, StableStore, SnapshotStore and a freshly connected transport, matching the target's own RaftEnv.Restart pattern) and validates that the fresh subject keeps the same LocalID; the seam does not implement protocol catch-up.
- After Restart, the fresh subject is re-wired to every controller carried by the shared Config (TimeController.attach, RandomController, MessageController via CapturingTransport) and the pause gates are per-runtime fields, so no stale hook from the old runtime can act.
- Pending MessageController entries are controller-owned and survive lifecycle changes; Inject to a stopped/crashed target fails with ErrTargetUnavailable and preserves the entry (existing message-controller behavior, unchanged by this unit).
- Paused subjects are removed from their TimeController subject set with their timers kept, so they receive no time steps while paused and resume with pending timers intact; stopped/crashed subjects are detached by the existing Shutdown wiring (tc.detach).
- The controller is inactive by default: it spawns no goroutines and no hook acts unless a method is called; nodes never attached to a LifecycleController behave exactly as before.
- ErrLifecycleUnsupported is exported and errors.Is-classifiable per the fixed_surface contract; no current operation needs it because all five operations are implementable (Pause/Resume via default-disabled core hooks, Stop/Crash/Restart as facades over tracked stop paths).
- Post-change limitation: goroutines owned by the transport (inmemPipeline.decodeResponses) or informational monitors (emitLogStoreMetrics, snapshot restore monitors) are not members of the raft routinesGroup; they are stopped by transport close / StopAndWait on the stop path and perform no protocol-state mutation, but they are not individually awaited by waitShutdown.
- Post-change limitation: response watcher goroutines created per captured request live until the corresponding response arrives or the decorator closes, so a long-running controlled session that injects many requests without transport shutdown can accumulate goroutines (a resource cost, not a correctness violation).

### 已覆盖路径

- Stop -> Restart: LifecycleController.Stop(target) -> Raft.Shutdown()/future.Error() -> durable stores retain term/log/snapshot/config -> LifecycleController.Restart(target) -> fresh NewRaft with same LocalID, stores and re-connected transport
- Crash -> Restart: LifecycleController.Crash(target) -> target's own stop primitives (no shutdown-time protocol-state flush; Raft persists term/vote/logs eagerly; transport close only resolves in-flight RPC waits) -> fresh runtime over pre-crash durable state -> LifecycleController.Restart(target)
- Pause/Resume on follower/candidate/leader main loops: top-of-loop and post-receive pause gates in every select case of runFollower, runCandidate and leaderLoop (raft.go), so a protocol message, timer or internal channel event received after Pause sets the paused flag is held at the gate in the receiving goroutine and not handled until Resume
- Pause/Resume on replication goroutines: top-of-loop and post-receive gates in replicate, heartbeat, pipelineReplicate and pipelineDecode (replication.go); pipelineReplicate post-receive gates use break SEND (the function returns error) matching the top-of-loop gate
- Pause/Resume on runFSM: top-of-loop and post-receive gates after the fsmMutateCh and fsmSnapshotCh receives (fsm.go) so FSM applies/restores/snapshot requests received after Pause are held before touching the application FSM
- Pause/Resume on runSnapshots: top-of-loop and post-receive gates after the snapshot-interval timer and userSnapshotCh receives (snapshot.go) so snapshot work received after Pause is held
- Stop/Crash while paused: Shutdown closes shutdownCh and every pause gate selects on shutdownCh, so termination completes from a paused state and a held event is dropped
- Paused subjects excluded from TimeController steps: LifecycleController.Pause calls TimeController.pause (timers kept but not delivered), Resume calls TimeController.resume, so no steps reach a paused subject
- Restart identity validation: fresh subject's LocalID must equal the old subject's LocalID, else Restart fails
- Crash boundary with tracked transfer contexts: the leadership-transfer watcher and the leadershipTransfer goroutine are registered through r.goFunc (raft.go:815 and raft.go:873), so Raft.Shutdown's waitShutdown (routinesGroup.Wait) awaits them; after Crash returns no abandoned execution context can respond to the transfer future or mutate the transfer-in-progress flag
- Regression: TestLifecycleController_CrashWaitsForLeadershipTransfer starts a real leadership transfer to a dead peer, crashes the leader, and asserts the transfer-in-progress flag is cleared and the transfer future resolves by the time Crash returns
- Regression: TestLifecycleController_PauseHoldsEventsReceivedAfterPause drives runFollower on a skipStartup node with a TimeController and verifies an apply enqueued after Pause returns is not responded while paused and is handled (ErrNotLeader) only after Resume

### 未覆盖路径

- Strict zero-latency pause: an event already received and past its post-receive gate check at the moment Pause sets the paused flag may complete its handling concurrently with Pause returning; every event received afterwards is held until Resume (inherent linearization point of a Go select-based loop; documented in the controller doc comment)
- The leaderLoop group-commit drain (GROUP_COMMIT_LOOP nested select) runs inside a case body that already passed its post-receive gate; applies drained there after Pause returns complete as part of the already-started handler (same linearization point)
- Informational telemetry (emitLogStoreMetrics goroutine) and in-flight transport RPC waits are not gated while paused (outside the protocol plane / already in flight at pause time)
- Transport-owned goroutines (inmemPipeline.decodeResponses, snapshot restore monitors) are stopped by pipeline Close / StopAndWait on the stop path, not by the pause gates; they are informational or resolve on transport close

### 实际实现方式

- core_hook: default-disabled pause gates (lifecyclePauseGate) at the top of every state loop and replication/snapshot/FSM goroutine AND immediately after every select receive, before the received event is handled; backed by per-node pause fields (pauseMu/paused/resumeCh) on the Raft struct
- core_hook (review revision): the leadership-transfer watcher and the leadershipTransfer goroutine are now started through r.goFunc instead of plain go, so Raft's goroutine group tracks them and Shutdown's waitShutdown waits for them; this closes the crash boundary without changing protocol, persistence, state-transition or ordering semantics
- facade: Stop and Crash wrap Raft.Shutdown + shutdownFuture.Error(); Restart wraps NewRaft through a consumer-supplied RestartFunc with a LocalID identity check
- integration: TimeController.pause/resume added (unexported) so paused subjects receive no time steps while their timers stay registered

### 修改前已知限制（供对照）

- After Shutdown, InmemTransport is closed (DisconnectAll); Restart must re-Connect peers (cluster.FullyConnect pattern, testing.go:518).
- Crash must resolve in-flight transport RPC goroutines (electSelf askPeer, inmemPipeline decodeResponses) so 'no abandoned execution context' holds; with a frozen virtual clock these would otherwise never complete.
- Raft persists term and vote eagerly (raft.go:2141-2147, persistVote at 2130), so 'no extra protocol-state flush on crash' is naturally satisfied; only state already written to LogStore/StableStore/SnapshotStore survives.
- The package's cluster harness (MakeCluster) returns the unexported *cluster type, so external consumers must assemble nodes manually (NewRaft + NewInmemTransport + NewInmemStore + FileSnapTest-equivalent).

## 状态观察

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Per-*Raft-node typed state views and the observer mechanism inside system_boundary (no cross-node global snapshot promised)
- 修改前测试接口是否完整：是
- 修改前测试支持判断：All required observations (role, term, commit_index, applied_index, log ranges via the owned store) are available through exported, documented, thread-safe APIs; no controller or snapshot schema is needed.

### Analyzer 发现的实现路径（修改前）

- per-node status views: State/Stats/CurrentTerm/CommitIndex/AppliedIndex/LastIndex/LeaderWithID/LastContact/GetConfiguration/observer channel, each read independently (no simultaneous cross-subject freeze)

### 目标已有入口

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

### 当前限制

- Separate getters are read independently; there is no simultaneous multi-field or multi-node snapshot - disclose temporal inconsistency.
- GetConfiguration returns the latest (possibly uncommitted) configuration (api.go:897); Stats() labels it 'latest_configuration'.
- AppliedIndex reflects entries sent to the FSM channel, not necessarily consumed by the application FSM (api.go:1238-1247).
- MockFSM.Logs()/configurations are exported but documented as 'not a stable API' (testing.go:36-107); the cluster harness (MakeCluster) returns the unexported *cluster type and is unusable outside the package.

## 外部输入

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Public Raft API and protocol state loops, Transport abstraction, InmemTransport, observer/future mechanisms, module-provided in-memory stores/snapshots, package-provided in-process testing support (excluding NetworkTransport/TCP sockets, external durable stores, application FSM semantics, process supervision, fuzzy/raft-compat/bench)
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The entrypoints are exported, documented, and directly callable by the declared test consumer; completion semantics and result mechanisms (Future.Error/Index/Response) are public. Excluded per contract: BootstrapCluster (bootstrap), Restore (restore), Snapshot (administration), Barrier (barrier), VerifyLeader (leadership check), GetConfiguration (configuration query), LeadershipTransfer (administration), Stats/State/observer (observation).

### Analyzer 发现的实现路径（修改前）

- proposal: Raft.Apply/ApplyLog([]byte|Log, timeout) -> applyCh -> dispatchLogs -> StoreLogs -> commit -> fsmMutateCh -> FSM.Apply -> ApplyFuture.Error()/Index()/Response()
- membership change: Raft.AddVoter/AddNonvoter/RemoveServer/DemoteVoter(ServerID, ..., prevIndex, timeout) -> configurationChangeCh -> appendConfigurationEntry -> LogConfiguration dispatch/commit -> IndexFuture

### 目标已有入口

- `Raft.Apply`
- `Raft.ApplyLog`
- `Raft.AddVoter`
- `Raft.AddNonvoter`
- `Raft.RemoveServer`
- `Raft.DemoteVoter`
- `Raft.AddPeer`
- `Raft.RemovePeer`

### 当前限制

- Apply/Barrier/Restore accept caller deadlines (timeout duration) that only bound enqueue; they do not bound commit completion.
- AddPeer/RemovePeer are deprecated and return ErrUnsupportedProtocol for ProtocolVersion > 2 (api.go:908-936).
- Apply must run on the leader; followers get ErrNotLeader; mid-flight leadership loss yields ErrLeadershipLost with unknown write outcome (api.go:804-821).

## 独立 Reviewer 结论

- 总体结论：`PASS`

### 非阻塞剩余风险

- Crash and Stop converge to the same underlying mechanism (both call Raft.Shutdown + shutdownFuture.Error). This is a target-specific reality: Raft.Shutdown is documented as 'not a graceful operation' and Raft persists term/vote/log eagerly, so there is no shutdown-time protocol-state flush and no distinct durable-state difference between the two; the controller records the phase (stopped vs crashed) only for transition validation. Consumers that require observably different durable state after Stop versus Crash will not get it from this target.
- MessageController.Clear() does not cancel response-watcher goroutines for requests that were already successfully injected (those requests have left c.entries, so Clear cannot close their droppedCh). If a response to such an in-flight request arrives after Clear, it is recorded into the now-cleared cache, and the watcher goroutine can persist until the decorator is closed. This is a resource/late-capture nuance rather than a lost-entry violation, since the response was not yet pending at Clear time.
- TimeController.Advance's settle uses a bounded runtime.Gosched budget (512 iterations) to wait for rearmable timers to re-arm between steps. A consumer that is genuinely blocked (for example inside a transport RPC whose virtual timeout is due at a later step) is not re-armed until it unblocks; this matches the boundary a sequence of separate Advance(1) calls would expose to a descheduled consumer, but it is a scheduling-heuristic rather than a hard scheduler-independent guarantee.
- PendingMessage exposes only the Response command for captured responses; the RPCResponse.Error component of an error-only response (where Response is nil) is not visible through Pending(). The private entry retains the error for injection, and normal raft responses carry a non-nil typed response even when an error is set.
- Pause has a documented linearization point: an event whose receive and post-receive gate check both completed before Pause set the paused flag may finish handling concurrently with Pause returning. Every event received after the flag is set is held at a gate; this is inherent to a select-based Go loop and does not leave the subject active.
- Crash/Stop can block for up to the in-boundary transport timeout while in-flight RPC waits resolve (TimeoutNow uses 10*i.timeout, up to 5s with default 500ms real-clock timeout) because the leadership-transfer goroutines are now awaited via routinesGroup. This is bounded and preserves the no-abandoned-context guarantee but is not instantaneous under the real clock.
- CapturingTransport peer wiring requires connecting the raw InmemTransports underneath the decorators (rawA.Connect(addrB, rawB)); the decorator's WithPeers.Connect delegates to the wrapped transport and will panic if handed another decorator, so callers must follow the documented raw-connect pattern.
