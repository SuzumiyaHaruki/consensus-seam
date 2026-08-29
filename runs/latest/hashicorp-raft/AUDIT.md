# hashicorp-raft 测试接口审计报告

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
Analyzer 内容描述修改前状态；生成接口和 Reviewer 内容描述候选修改后状态。
机器可读细节以`capability-report.json`、`interface-report.json`、`review-report.json`为准。

## 消息捕获

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Same system boundary: logical cross-node messages inside the boundary flow exclusively through the Transport abstraction (InmemTransport in boundary); real TCP transports are outside.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：There is no MessageController, MessageHandle, MessageKind, PendingMessage, or capture seam anywhere in the module (search for Controller returns nothing); the test consumer would have to hand-write all interception, so the fixed surface must be added.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- append_entries: leader replicate/heartbeat/pipeline -> Transport.AppendEntries / AppendEntriesPipeline (replication.go:231, 412, 446-508) -> target consumerCh -> rpcCh -> Raft.processRPC -> appendEntries (raft.go:1440) -> RPC.Respond -> RespChan
- request_vote: electSelf -> Transport.RequestVote (raft.go:2001) -> target requestVote handler -> RequestVoteResponse
- request_prevote: preElectSelf -> Transport.RequestPreVote via WithPreVote (raft.go:2080) -> requestPreVote handler -> RequestPreVoteResponse
- install_snapshot: sendSnapshot -> Transport.InstallSnapshot with stream Reader (raft.go sendSnapshot) -> installSnapshot handler -> InstallSnapshotResponse
- timeout_now: leadershipTransfer -> Transport.TimeoutNow (raft.go:990 leadershipTransfer) -> timeoutNow handler -> TimeoutNowResponse

### Analyzer 建议（修改前）

- Add MessageController, MessageHandle (struct backed by unexported uint64), MessageKind (underlying string), PendingMessage{Handle, Source ServerID, Target ServerID, Kind, Message}, NewMessageController, Pending() []PendingMessage, Drop(handle) error, Clear(), plus a Transport wrapper installed as the Transport passed to NewRaft (before goroutines start at api.go:622-624).
- Capture outbound requests at the wrapper (AppendEntries/RequestVote/RequestPreVote/InstallSnapshot/TimeoutNow/pipeline) with per-target Source/Target from the wrapper's configured ServerID/ServerAddress; keep the caller blocked on its original response continuation, and replace RespChan with a controller channel so responses are recorded as new pending entries (reversed Source/Target, new handle) and only forwarded to the original caller on that entry's Inject.
- Add a typed TargetMessage variant wrapper over the ten command types and deep-copy nested slices/maps/pointers; buffer InstallSnapshot Readers into independently replayable memory/temp-file storage released when the entry leaves.
- The cache must be thread-safe, keep acceptance order, and never silently evict; Drop/Clear/Inject leave other entries' order untouched.

### 目标已有入口

- `Transport.Consumer`
- `Transport.AppendEntries`
- `Transport.RequestVote`
- `Transport.RequestPreVote`
- `Transport.InstallSnapshot`
- `Transport.TimeoutNow`
- `Transport.AppendEntriesPipeline`
- `InmemTransport.Connect`

### 本次生成接口

- 捕获位置：`controlled_transport.go / ControlledTransport：Outbound Transport calls (AppendEntries, RequestVote, RequestPreVote, InstallSnapshot, TimeoutNow, AppendEntriesPipeline) are intercepted before the real InmemTransport makeRPC send path; inbound responses are intercepted at the controller's respCh watcher after the target ingress has answered.`
- Pending Store：`message_controller.go / MessageController：Ordered pending slice plus byHandle map guarded by mu; each entry holds the private deep copy, the buffered replayable stream, routing address, and the response continuation; the injecting flag serializes delivery.`
- 公开入口：`message_controller.go / NewMessageController：Constructor of the shared, thread-safe MessageController; controlled mode is disabled by default so production behavior is unchanged.`
- 公开入口：`message_controller.go / MessageController.SetControlled：Enables/disables capture; when disabled, wrapped transports delegate every call.`
- 公开入口：`message_controller.go / MessageController.Pending：Returns a fresh deep snapshot (including Stream) of all captured messages in stable controller acceptance order.`
- 公开入口：`message_controller.go / MessageController.Drop：Removes one pending entry without delivering it; invalidates its handle and never reorders the remaining entries.`
- 公开入口：`message_controller.go / MessageController.Clear：Removes every pending entry without delivering any.`
- 公开入口：`message_controller.go / PendingMessage：Public view: Handle, Source/Target ServerID, Kind, typed MessagePayload content, and the deep-copied Stream snapshot.`
- 公开入口：`message_controller.go / MessageHandle：Struct backed by an unexported uint64 identity; stable while pending, never reused.`
- 公开入口：`message_controller.go / MessageKind：String-based kind classification of the ten request/response message families.`
- 公开入口：`controlled_transport.go / NewControlledTransport：Wraps one InmemTransport with the local ServerID and the shared controller; install as the node's Transport before NewRaft.`
- 公开入口：`controlled_transport.go / ControlledTransport：Transport/WithPreVote/WithPeers/WithClose (LoopbackTransport) wrapper that intercepts outbound AppendEntries, RequestVote, RequestPreVote, InstallSnapshot, TimeoutNow, and AppendEntriesPipeline.`

### 使用与范围

- 生产路径：Unchanged: without a controller, or while SetControlled(false), ControlledTransport delegates every call to the wrapped InmemTransport; NewMessageController starts disabled.
- 测试路径：Focused same-package tests in message_controller_test.go: round trip incl. stream snapshot deep-copy, drop/clear/errors, target unavailable, two-node end-to-end election and commit, concurrent single-delivery, and the new TestMessageControllerDropAndInjectPreserveOrder (Drop and successful Inject of a middle entry leave the acceptance order of the remaining entries intact) and TestMessageControllerClosedOwnerRebind (closed-owner Inject fails deterministically with ErrMessageNotAccepted and preserves the entry; re-binding the entry to a fresh wrapper of the same node makes the same handle deliverable again).
- 缓存实例引用：One MessageController per test cluster; each node's ControlledTransport binds to it. A MessageHandle identifies one concrete entry and remains stable while pending; identities are never reused after removal.
- 目标绑定方式：The captured target address is resolved at Inject through the owning wrapper's base InmemTransport peers map, the same routing table InmemTransport.makeRPC uses; ServerIDs come from the transport call arguments (target id) and the wrapper's local ID (source).
- 缓存变化与失败语义：Capture appends one entry per outbound transport call (broadcast expands per concrete target in stable controller acceptance order). Drop removes one entry and Clear removes all; removal is order-preserving (append-slice delete), so Drop, Clear, and Inject never reorder the remaining entries. A successful Inject removes the request entry, invalidates its handle, and later records the protocol response as a new pending entry with a fresh handle. Copy or stream-buffer failures are returned to the caller and register nothing in the cache. Handles are never reused and entries are never silently evicted, retargeted, or reordered.
- 复制策略：Deep copy at producer-to-controller capture (typed payloads including RPCHeader ID/Addr, Leader/Candidate, and Entries []*Log with Data/Extensions; InstallSnapshot streams fully buffered into replayable memory) and a fresh deep copy at every Pending call, including the new PendingMessage.Stream field, so Pending returns complete independent snapshots. Inject always delivers the controller's private copy and replays streams from the private buffer via bytes.NewReader; mutating a Pending snapshot (payload or stream) never affects delivery.
- Blocking review issue resolved: removeLocked now deletes with append(c.pending[:i], c.pending[i+1:]...), so Pending preserves controller acceptance order and Drop/Inject do not reorder other entries (verified by TestMessageControllerDropAndInjectPreserveOrder, including a middle-entry Drop and a middle-entry Inject with response entries appended in acceptance order)
- Blocking review issue resolved: Inject no longer selects on owner.closedCh against a permanently-ready closed channel; it pre-checks the owner once (deterministic ErrMessageNotAccepted, entry preserved) and LifecycleController.Restart re-binds pre-stop/crash entries to the fresh wrapper via the new unexported MessageController.rebindOwner, so post-restart injection of a pre-crash pending message is deterministic and delivers through the normal ingress (verified by TestMessageControllerClosedOwnerRebind and the end-to-end TestLifecycleControllerRestartKeepsPendingInjectible, where a TimeoutNow captured before Crash is injected after Restart, node2 answers through its live ingress, and the handle is invalidated on acceptance)
- Source of a captured request is the wrapper's ServerID; Target comes from the transport call's id argument (the target ServerID), exactly as Raft invokes the Transport interface
- InmemTransport.SetHeartbeatHandler is a no-op (inmem_transport.go), so heartbeats arrive on the consumer channel and are captured like any other AppendEntries
- A controlled call blocks until its captured response entry is injected, bounded by the underlying transport timeout (10x for InstallSnapshot/TimeoutNow), mirroring InmemTransport.makeRPC; this also prevents Raft.Shutdown from deadlocking on held exchanges
- Closing the owning transport (Stop/Crash) unblocks the original blocked caller with a transport-shutdown error (the old runtime is gone) while the captured entry itself stays pending for the tester
- Real TCP/network transports, external durable stores, and raft-compat/fuzzy/bench are outside the system boundary and are never wrapped
- Handles are monotonic and never reused; Pending/Drop/Clear/Inject never advance time; entries are never silently evicted, retargeted, or reordered
- No Take, mutable cache exposure, message mutation, redirection, duplication, fabrication, selection policy, acknowledgements, commit waiting, or quiescence waiting is provided
- Remaining disclosed limitation: the wrapper's send/wait and Inject enqueue deadlines remain wall-clock based (RPC delivery deadlines, not protocol timers); they never gate protocol state transitions and are outside the time-control capability scope

### 已覆盖路径

- append_entries: leader replicate/heartbeat -> ControlledTransport.AppendEntries -> captured pending entry; Inject -> target consumerCh -> processRPC -> appendEntries -> Respond -> response captured as new pending entry -> response Inject completes the original caller
- request_vote: electSelf -> ControlledTransport.RequestVote -> one captured entry per target voter (broadcast expands per target)
- request_prevote: preElectSelf -> ControlledTransport.RequestPreVote -> captured per target
- install_snapshot: sendLatestSnapshot -> ControlledTransport.InstallSnapshot buffers the stream at capture; Pending exposes a deep-copied stream snapshot; delivery replays the controller's private buffer
- timeout_now: leadershipTransfer -> ControlledTransport.TimeoutNow -> captured
- append_entries_pipeline: pipelineReplicate -> ControlledTransport.AppendEntriesPipeline -> controlledPipeline.AppendEntries captures each request; the AppendFuture completes only when the captured response entry is injected

### 实际实现方式

- Transport wrapper installed as each node's Transport before NewRaft; pure delegate while SetControlled(false), so production defaults are untouched
- Capture at the outbound transport call with deep-copied typed payloads (RPCHeader/Leader/Candidate/Peers/Configuration byte slices and Entries []*Log with Data/Extensions); InstallSnapshot streams are fully buffered into replayable memory at capture
- Synchronous callers, channels, and futures are preserved: each entry carries a private response continuation; responses are separately captured as new pending entries with reversed Source/Target and a fresh handle
- Order-preserving pending-store removal: removeLocked uses append(c.pending[:i], c.pending[i+1:]...) so Drop/Clear/Inject never reorder surviving entries
- Deterministic closed-owner handling: Inject checks owner.closedCh once before delivery (instead of racing a permanently-ready closed channel inside the enqueue select), so an entry whose owning transport was closed by Stop/Crash fails deterministically with ErrMessageNotAccepted and is preserved
- Post-restart ownership: LifecycleController.Restart creates a fresh ControlledTransport and re-binds every pending entry captured through the old wrapper via MessageController.rebindOwner, so pre-stop/crash handles stay injectable through the fresh transport of the same node
- Same-package reuse of InmemTransport routing (peers map, consumerCh, timeout) so capture and injection share the normal protocol ingress

### 修改前已知限制（供对照）

- No common message struct exists; RPC.Command is interface{} (transport.go:19), so the patch must add a typed variant carrier (TargetMessage) over *AppendEntriesRequest/Response, *RequestVoteRequest/Response, *RequestPreVoteRequest/Response, *InstallSnapshotRequest/Response, *TimeoutNowRequest/Response (commands.go) to avoid bare any.
- Requests carry nested pointers (Entries []*Log) and InstallSnapshot carries a stream (RPC.Reader), so producer->controller and controller->Pending deep copies plus replayable stream storage must be added by the patch.
- Sender-side InmemTransport timeouts (inmem_transport.go:185, 196, 279, 323) arm real timers while a response is held; the wrapper should capture at the outbound call so the real transport is not invoked until Inject, and/or transport timeouts must be virtualized by the TimeController.
- InmemTransport.SetHeartbeatHandler is a no-op (inmem_transport.go:74), so heartbeat AppendEntries arrive via Consumer and are captured; NetTransport heartbeats are out of boundary.
- Self-votes (raft.go:2020-2035) are local and correctly excluded as non-cross-node.
- Broadcast naturally expands per target: electSelf loops per voter (raft.go:2015-2040) and replication is one goroutine per peer (startStopReplication raft.go:582-645).

## 消息注入

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Same system boundary: injection resolves real in-boundary targets (InmemTransport peers) and uses the normal Consumer-channel ingress; TCP transports are outside.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：No Inject exists; the primitive surfaces (transport calls, consumer channel, RespChan) require the test consumer to hand-write interception and forwarding, which the fixed controller surface must provide.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- append_entries: Inject -> resolve captured target peer -> enqueue RPC (original Command/Reader + controller RespChan) into target consumerCh (normal ingress, inmem_transport.go:183-188) -> Raft.processRPC -> response -> controller records response entry -> response Inject forwards to original RespChan
- request_vote / request_prevote / install_snapshot / timeout_now: same controller-owned instance and same end-to-end path as capture, per message family

### Analyzer 建议（修改前）

- Add Inject(handle MessageHandle) error on MessageController plus errors ErrMessageNotPending, ErrTargetUnavailable, ErrMessageNotAccepted (errors.Is-classifiable).
- Inject resolves the real captured target through the wrapper's routing (InmemTransport.peers by ServerAddress), enqueues the controller's private deep copy into the target consumerCh, and on confirmed acceptance removes the entry and invalidates the handle; any error preserves the entry and handle.
- Inject succeeds on enqueue acceptance and does not wait for dequeue, state transition, response, commit, or quiescence; later protocol failure does not restore the entry.

### 可参考的源码位置

- `inmem_transport.go:166`：Normal ingress resolution: peers map keyed by ServerAddress (line 44) with enqueue into peer.consumerCh; injection must use this same routing so a request reaches its request ingress rather than fabricated completion.
- `transport.go:25`：Responses flow back on RPC.RespChan; the wrapper keeps the original continuation live by holding it until the response entry is injected.

### 本次生成接口

- 捕获位置：`controlled_transport.go / ControlledTransport：Injection re-enters the same wrapper-owned seam: the entry recorded at the outbound Transport call is delivered into the real target's consumer channel (the normal ingress InmemTransport.makeRPC uses).`
- Pending Store：`message_controller.go / MessageController：The same ordered pending slice and byHandle map used by capture; Inject updates this same instance (same end-to-end path) and uses the injecting flag for single-delivery serialization.`
- 公开入口：`message_controller.go / MessageController.Inject：Delivers one pending entry through its captured target's normal input boundary and updates the same cache; classification errors ErrMessageNotPending, ErrTargetUnavailable, ErrMessageNotAccepted; single-delivery under concurrent calls; closed-owner entries fail deterministically and are preserved until re-bound.`
- 公开入口：`message_controller.go / ErrMessageNotPending：errors.Is-classifiable sentinel for handles that are not currently pending (never captured, dropped, cleared, injected, or being injected concurrently).`
- 公开入口：`message_controller.go / ErrTargetUnavailable：errors.Is-classifiable sentinel when the captured target is not reachable through the normal routing table.`
- 公开入口：`message_controller.go / ErrMessageNotAccepted：errors.Is-classifiable sentinel when the target's input boundary did not accept the message (enqueue timeout, closed transport, or a closed owning transport).`

### 使用与范围

- 生产路径：Unchanged: injection only exists on controller-owned entries; with the controller disabled or absent, transports behave exactly as before.
- 测试路径：Covered by message_controller_test.go: round trip (request inject, response capture and inject), drop/clear/error classification, target-unavailable preservation, the two-node end-to-end Raft election/commit driven purely by Inject, TestMessageControllerConcurrentInjectDeliversOnce, TestMessageControllerClosedOwnerRebind (deterministic closed-owner ErrMessageNotAccepted with entry preservation, then successful delivery of the same handle after rebind to a fresh wrapper), and TestLifecycleControllerRestartKeepsPendingInjectible in lifecycle_control_test.go (TimeoutNow captured before Crash, Restart re-binds it, Inject delivers through the live peer ingress, the response is captured, and the handle is invalidated on acceptance).
- 缓存实例引用：One controller instance owns the cache; capture and injection operate on the same instance and the same declared end-to-end path per message; LifecycleController.Restart re-binds entries of a restarted node to its fresh wrapper on that same instance.
- 目标绑定方式：The captured ServerAddress is resolved against the owning wrapper's base InmemTransport peers map at Inject time (identifier arithmetic alone is never used); the resolved peer's consumerCh is the normal request ingress for that direction. After Restart the fresh wrapper wraps the same base transport, so re-connected routes resolve identically.
- 缓存变化与失败语义：Successful Inject removes the request entry, invalidates its handle, and then records the protocol response as a new pending entry. Invalid handle, unavailable target, explicit non-acceptance, or a closed owning transport return an error and preserve the entry and handle; a closed-owner refusal is deterministic (no race against a permanently-ready closed channel). Re-binding the entry to a fresh wrapper of the same node (LifecycleController.Restart) restores delivery. Later protocol failure never restores an accepted entry. Concurrent Inject calls on one handle deliver exactly once: one call succeeds, the others are refused with ErrMessageNotPending while the in-flight delivery decides the entry's fate.
- 复制策略：Inject delivers only the controller's private deep copy, never a Pending snapshot; InstallSnapshot streams replay from the private buffer; each Pending call still returns independent fresh copies (payload and Stream).
- Blocking review issue resolved: the enqueue select no longer contains case <-owner.closedCh (a permanently-ready channel after Stop/Crash); instead the owner is checked once before delivery, making the closed-owner outcome deterministic (ErrMessageNotAccepted, entry preserved), and LifecycleController.Restart re-binds pre-crash entries to the fresh wrapper so post-restart injection of the same handle delivers through the reconnected normal ingress (TestMessageControllerClosedOwnerRebind, TestLifecycleControllerRestartKeepsPendingInjectible)
- Acceptance is defined as successful enqueue into the target's consumerCh, matching InmemTransport semantics; Inject does not wait for dequeue, state transition, response, commit, or quiescence
- The target cannot distinguish acceptance from timeout at the enqueue layer, so an accepted entry is never restored, preventing duplicate delivery; later protocol failure does not restore it
- ErrTargetUnavailable is returned when the peer is disconnected (absent from the routing table); ErrMessageNotAccepted when the enqueue times out, the owning transport is closed, or the owning transport closed; all preserve the entry and handle
- A dropped response leaves its caller blocked until the transport-level wait resolves, mirroring a lost response on the real transport
- The response entry for a delivered request is captured asynchronously; the response watcher goroutine lives at most as long as the owning transport (it aborts on the owner's closedCh, which is the fresh wrapper after a restart)
- Remaining disclosed limitation: the Inject enqueue and the caller-block wait use the base transport's wall-clock send timeout (RPC delivery deadline, not a protocol timer); in loopback tests it completes immediately and never gates protocol state

### 已覆盖路径

- append_entries: Inject(request) -> resolve peer from owner.base.peers -> peer.consumerCh (normal ingress) -> Raft.processRPC -> appendEntries -> Respond -> response captured -> Inject(response) -> original caller completes
- request_vote: Inject(RequestVoteRequest entry) -> requestVote ingress -> RequestVoteResponse captured and forwarded on Inject
- request_prevote: Inject(RequestPreVoteRequest entry) -> requestPreVote ingress -> RequestPreVoteResponse captured and forwarded on Inject
- install_snapshot: Inject(InstallSnapshotRequest entry) -> installSnapshot ingress with replayed private stream -> InstallSnapshotResponse captured and forwarded on Inject
- timeout_now: Inject(TimeoutNowRequest entry) -> timeoutNow ingress -> TimeoutNowResponse captured and forwarded on Inject
- append_entries_pipeline: Inject of a pipelined request entry -> target ingress -> response captured -> Inject completes the AppendFuture

### 实际实现方式

- Inject resolves the captured target through the owner's base InmemTransport peers map and enqueues the controller's private copy into the target consumerCh, the same ingress InmemTransport.makeRPC uses, bounded by the base transport send timeout
- Inject marks the entry injecting under the controller lock before delivery and clears the flag on every failure path, so a concurrent Inject of the same handle is refused with ErrMessageNotPending and the target ingress receives exactly one delivery
- Deterministic closed-owner failure: Inject checks the owning transport's closedCh once before delivery; a closed owner yields ErrMessageNotAccepted with the entry and handle preserved, and the closed channel is never used as a select case against a possibly-successful enqueue
- Post-restart ownership: LifecycleController.Restart creates a fresh ControlledTransport over the same base and controller and calls MessageController.rebindOwner, re-assigning every pending entry captured through the old wrapper to the fresh one so pre-stop/crash handles remain injectable
- Response entries inject by forwarding the stored RPCResponse to the original caller's continuation (waitCh), unblocking the synchronous transport call or completing the pipeline AppendFuture; responses always come from the real target handler, never fabricated
- Confirmed acceptance removes the entry and invalidates its handle; invalid handle, unavailable target, or explicit non-acceptance preserve the entry

### 修改前已知限制（供对照）

- Acceptance is defined as successful enqueue into the target's consumerCh (inmem_transport.go:183-188); the target cannot distinguish acceptance from timeout at that layer, so the patch must use enqueue success as the acceptance signal and never restore an entry after acceptance to avoid duplicate delivery.
- If the test blocks a request before the real transport call (outbound capture), injection must perform the real call with a fresh RespChan and capture the response as a new pending entry; the original caller's synchronous future stays blocked until that response entry is injected (no orphaned callers).
- Handle validity: stable while pending; invalid after Drop, Clear, or successful Inject; the patch must not reuse identities.

## 时间控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Same system boundary: protocol-relevant clocks/timers inside the module (raft loops, replication, snapshot loop, InmemTransport delivery timeouts); metrics/logging timestamps and caller-side deadlines are excluded unless they feed protocol behavior.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：All protocol timing is hardwired to the wall clock (time.After/time.Now/time.Since) with no clock abstraction, no Tick, and no public pre-start hook; the test consumer cannot freeze or step protocol time today.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- node_follower_loop: heartbeatTimer via randomTimeout (raft.go:163, 217) and time.After(0) (raft.go:211), time.Since(lastContact) election trigger (raft.go:220-223)
- node_candidate_loop: electionTimer via randomTimeout (raft.go:310, 353, 426)
- node_leader_loop: lease time.After(LeaderLeaseTimeout) (raft.go:677, 947), checkLeaderLease time.Now (raft.go:1047), leadership-transfer timers (raft.go:728, 749)
- node_replication_goroutines: commit timeout and heartbeat interval randomTimeout (replication.go:169, 402, 495), backoff time.After (replication.go:213, 419)
- node_snapshot_loop: randomTimeout(SnapshotInterval) (snapshot.go:75)
- inmem_transport_delivery: send/response timeouts time.After (inmem_transport.go:185, 196, 279, 323)

### Analyzer 建议（修改前）

- Add TimeController, NewTimeController(...), and Advance(steps uint64) error plus a Clock abstraction (Now/After) defaulting to real time, installed through a new public Config field so control is in place before NewRaft launches goroutines (api.go:622-624).
- Route all protocol-relevant timer sites through the injected clock (raft.go:163/211/217/220-223/310/353/426/677/728/749/947/1047, replication.go:169/213/402/419/495, snapshot.go:75, util.go:34-40, inmem_transport.go:185/196/279/323) as disclosed no-op-by-default core hooks.
- Implement Advance(n) as n unit steps that advance a shared virtual clock, wake due timers in order (re-arming earlier-step timers before later steps), and skip paused/stopped/crashed nodes; Pending/Inject/Drop/Clear/observation/external input never advance time.

### 可参考的源码位置

- `raft.go:163`：Follower heartbeat timer is a protocol time source: heartbeatTimer = randomTimeout(HeartbeatTimeout), with time.Since(lastContact) (line 220-223) deciding the transition to Candidate.
- `raft.go:310`：Election timer (randomTimeout) drives candidate re-election; part of the protocol timing paths.
- `raft.go:677`：Leader lease timer (time.After(LeaderLeaseTimeout), renewed at line 947) and checkLeaderLease time.Now (line 1047) gate stepping down; all are protocol-relevant clock reads.
- `config.go:243`：The only startup-suppression switch is unexported (used by GetConfiguration at api.go:448), so an external consumer needs a public constructor-time installation point (e.g., a Clock field on Config) before NewRaft starts goroutines at api.go:622-624.

### 本次生成接口

- 捕获位置：`time_controller.go / nodeClock：Per-node attribution wrapper created by NewRaft when Config.Clock is a TimeController's virtual clock: every timer armed by the node (heartbeat, election, lease, commit, snapshot, backoff, followerNotifyCh) is tagged with the node so Advance can exclude paused, stopped, and crashed nodes at delivery.`
- Pending Store：`time_controller.go / virtualClock：The virtual clock's pending-timer heap is the only store: timers are removed from the heap exactly when they fire at their step boundary, held timers of paused nodes are re-pushed for later boundaries, and stale timers of stopped/crashed runtimes are discarded when due, so a timer can never fire twice, be silently dropped while its node runs, or be reordered relative to equal-deadline timers (arm order preserved).`
- 公开入口：`time_controller.go / TimeController：System-level controller owning one shared virtual clock with a fixed step unit; in controlled mode Advance is the only way protocol time progresses.`
- 公开入口：`time_controller.go / NewTimeController：NewTimeController(unit time.Duration, nodes ...*Raft) *TimeController creates the controller and its shared virtual clock; unit is the target-defined duration of one Advance step; panics on a non-positive unit. Nodes created later are wired through Config.Clock.`
- 公开入口：`time_controller.go / TimeController.Advance：Advance(steps uint64) error advances the shared clock one unit at a time; after each unit every timer whose deadline is reached at that boundary is submitted in (deadline, arm-order), except that timers of paused nodes are held and timers of stopped/crashed runtimes are discarded. Advance(n) equals n separate Advance(1) calls including re-armed timers; returns after due events are submitted, not after processing.`
- 公开入口：`time_controller.go / TimeController.Clock：Clock() Clock returns the shared virtual clock to install in each controlled node's Config.Clock before NewRaft starts the node's goroutines.`
- 公开入口：`time_controller.go / TimeController.Register：Register(node *Raft) error records a controlled node (ServerID-keyed; rejects nil and duplicates) for bookkeeping and restart re-binding; lifecycle-aware step exclusion itself comes from the per-node timer attribution installed by NewRaft.`
- 公开入口：`time_controller.go / Clock：Clock interface with Now() time.Time and After(d time.Duration) <-chan time.Time; realClock is the default (delegates to time.Now/time.After), virtualClock is the controller's shared clock.`
- 公开入口：`config.go / Config.Clock：Config field installing a Clock (e.g. TimeController.Clock()) on a node before NewRaft; nil (default) keeps the real wall clock and production behavior.`

### 使用与范围

- 生产路径：Config.Clock nil (default): NewRaft installs realClock, so all routed sites behave exactly as upstream (time.Now/time.After); production behavior is unchanged and the TimeController is inert. With Config.Clock set, the nodeClock wrapper is transparent (same Now/After semantics) and only adds lifecycle-aware delivery in Advance.
- 测试路径：Config.Clock = tc.Clock() installed before NewRaft: protocol time is fully controlled; only TimeController.Advance progresses it. Focused tests cover no-auto-progress, Advance-driven election, step boundaries/order/single-fire, re-armed timers, Register, and the new TestTimeControllerSkipsPausedAndStoppedNodes (paused node receives no steps across Advance(500); held timers drive the election after Resume; Advance after Stop discards stale timers without hanging).
- 缓存实例引用：One shared virtualClock per TimeController, created in NewTimeController and referenced by every node whose Config.Clock was set to tc.Clock(); the reference is stable for the controller's lifetime. Each node's runtime additionally holds a nodeClock wrapper bound to that node (fresh wrapper per NewRaft), so restart re-attribution happens automatically.
- 目标绑定方式：Not a message-target capability: NewRaft binds the shared virtual clock to the node by wrapping it in a nodeClock that holds the concrete *Raft; Advance reads that binding (paused flag and RaftState) directly, so exclusion works for every node wired through Config.Clock without registry lookups and survives LifecycleController.Restart.
- 缓存变化与失败语义：No message cache. Advance moves the shared clock; at each boundary due timers are classified: running-node timers fire once, paused-node timers are held (fired on a later Advance after Resume), stopped/crashed-runtime timers are discarded. Unattributed timers armed directly on the shared clock always fire. Pending/Inject/Drop/Clear/observation/external input never advance time.
- 复制策略：No payload copying: timer channels carry the virtual deadline time.Time value and are delivered exactly once; nothing aliases node state.
- Implementation is a facade over a shared virtual clock plus narrow no-op-by-default core hooks: every protocol-relevant timer/time-check site (raft.go, replication.go, random_controller.go randomTimeoutFor) is routed through the node's Clock, which defaults to the real wall clock; no protocol, persistence, state-transition, or ordering semantics changed, and production defaults are preserved.
- Installation boundary satisfied: NewTimeController is constructed first, its Clock() is set on each node's Config.Clock, and NewRaft stores it (and wraps it with the nodeClock) before launching goroutines; there is no uncontrolled time window and no same-package test switch.
- Step semantics: one step advances the shared clock by one unit, then submits all timers due at that boundary in (deadline, arm-order); Advance(n) is a loop of identical single-step boundaries, so timers re-armed in reaction to earlier steps fire at later steps and no timer is skipped or refired.
- Lifecycle-aware delivery: a due timer belonging to a paused node is held and re-evaluated at later boundaries (it fires only after Resume, on a later Advance); a due timer belonging to a stopped or crashed runtime is discarded so no stale timer of a discarded runtime is ever delivered; unattributed timers (tests arming the shared clock directly) fire exactly as before.
- Restart re-attribution is automatic: LifecycleController.Restart constructs the fresh runtime with the same Config.Clock, NewRaft binds a fresh nodeClock to the fresh *Raft, so old-runtime timers are discarded when due while the fresh runtime's timers fire normally.
- The virtual clock starts at time.Unix(0,0) for reproducibility; LastContact() and observed timer values are virtual times and must not be compared against the wall clock.
- After(0) (followerNotifyCh heartbeat reset) arms at the current boundary and fires on the next Advance step, consistent with 'protocol time does not progress without Advance'.
- Advance returns once due events have been submitted through the normal timer channels; it does not wait for their processing, resulting messages, state transitions, or commits (per completion contract).
- Thread safety: virtualClock serializes Now/After/advance with a mutex; timer channels are buffered and each timer fires exactly once; held-timer re-push keeps heap order; concurrent Advance and node re-arms are safe.
- RandomController integration: randomTimeoutFor draws the jitter then arms the timer through r.clock.After, so draws remain recorded while their firing is time-controlled.
- NewTimeController panics on a non-positive unit; Advance(steps) returns nil for valid input (0 steps is a no-op).

### 已覆盖路径

- node_follower_loop: heartbeatTimer arm and re-arm via Raft.randomTimeoutFor (raft.go) and followerNotifyCh reset now use r.clock.After; the election trigger check uses r.clock.Now().Sub(lastContact)
- node_candidate_loop: electionTimer arms and re-arms via randomTimeoutFor -> r.clock.After
- node_leader_loop: leader lease timer and checkLeaderLease time read use r.clock.After/r.clock.Now; leadership-transfer ElectionTimeout waits use r.clock.After
- node_replication_goroutines: commit and heartbeat-interval timers via randomTimeoutFor; failure backoff and heartbeat backoff via s.clock.After
- node_snapshot_loop: snapshot interval timer via randomTimeoutFor -> r.clock.After
- lifecycle_aware_step_exclusion: NewRaft wraps the shared virtual clock with a nodeClock; Advance holds timers of paused nodes (they fire on a later Advance after Resume) and discards timers of stopped/crashed runtimes when due, so paused, stopped, and crashed nodes do not receive steps
- production_default: Config.Clock nil -> NewRaft installs realClock, so every routed site behaves exactly as before (time.After/time.Now)

### 未覆盖路径

- inmem_transport_delivery_timeouts (inmem_transport.go) and controlled_transport/message_controller wrapper timeouts remain wall-clock based: they are RPC delivery deadlines, not protocol timers; they never gate protocol state transitions and in loopback tests complete immediately, so virtualization would require changing transport construction without protocol benefit
- caller_side_deadlines (Apply/AddVoter/etc. timeouts, requestConfigChange) stay real per the capability spec (caller-side deadlines excluded)
- metrics_and_logging_timestamps (dispatchLogs MeasureSince sites, emitLogStoreMetrics, Log.AppendedAt) stay real per spec (metrics only)
- per_node_step_skipping: exclusion is enforced at timer delivery and by the pause gates rather than by freezing each node's view of the shared clock; stopped/crashed nodes have no live protocol goroutines and their stale timers are discarded, and per-node drift/advancement is out of v0 scope

### 实际实现方式

- config_dependency_injection: public Config.Clock field consumed by NewRaft before goroutines start
- core_hook: no-op-by-default routing of all protocol timer/time-check sites through the injected Clock (disclosed, semantics-preserving)
- facade_wrapper: TimeController facade over a shared virtual clock implementing the Clock interface
- per-node attribution (core_hook, default-inert): NewRaft wraps a virtualClock with a nodeClock; virtualClock.advance gates delivery per timer by the owning node's paused flag and RaftState
- accessor: TimeController.Clock() for pre-NewRaft wiring; TimeController.Register for node bookkeeping
- target_language_tests: focused tests for no-auto-progress, Advance-driven election, step boundaries/order/single-fire, re-armed timers, Register, and lifecycle-aware step exclusion

### 修改前已知限制（供对照）

- Satisfying the complete contract requires core hooks in raft.go (runFollower/runCandidate/leaderLoop timers and time.Since/time.Now checks), replication.go (commit/heartbeat/backoff timers), snapshot.go, util.go (randomTimeout), and inmem_transport.go (delivery timeouts); each replacement is no-op-by-default and preserves ordering, transition conditions, and production behavior (allowed per spec, disclosed as core hooks, not INVASIVE).
- One Advance step must be mapped to a target-defined unit (e.g., a fixed tick duration) since the protocol is duration-based; Advance(n) must fire due timers in order without skipping intermediate events and must skip paused/stopped/crashed nodes.
- Excluded clock uses: metrics timestamps (metrics.MeasureSince), Log.AppendedAt (informational, log.go:96-107), emitLogStoreMetrics (log.go:177-192, metrics only), lastContact reporting, and caller-provided timeouts (Apply timeout etc.).
- The unexported skipStartup (config.go:243-244) does not close the public construction race; a public Config Clock field consumed by NewRaft before api.go:622-624 is required.
- Advance returns after due events are submitted through the normal timeout path, not after their processing or resulting state transitions (per contract).

## 随机性控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Same system boundary: the package's hidden non-cryptographic draws (global math/rand in randomTimeout) used by protocol loops; crypto/rand UUIDs and fuzzy/ subdirectory test generators are outside scope.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：randomTimeout uses the package-global math/rand with no per-node source, no seed API, no choice history, and no owner attribution; the declared test consumer cannot reproduce or observe the draws, so the fixed RandomController surface must be added.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- node_follower_loop: randomTimeout(HeartbeatTimeout) heartbeatTimer draws (raft.go:163, 217)
- node_candidate_loop: randomTimeout(ElectionTimeout) electionTimer draws (raft.go:310, 353, 426)
- node_replication_goroutines: randomTimeout(CommitTimeout) and randomTimeout(HeartbeatTimeout/10) draws (replication.go:169, 402, 495)
- node_snapshot_loop: randomTimeout(SnapshotInterval) draw (snapshot.go:75)

### Analyzer 建议（修改前）

- Add RandomController, NewRandomController(seed int64, ...), RandomChoice{Name string, Value TargetRandomValue}, and Choices() []RandomChoice in a new file.
- Add a no-op-by-default core hook: replace the global-rand use in randomTimeout (util.go:34-40) with a per-node seeded source installed via a new Config field read before NewRaft starts goroutines; same seed and draw order then reproduce election/heartbeat/commit/snapshot interval choices while the default keeps the global rand production behavior.
- Record every draw as a deep-copied RandomChoice attributed to its node (concrete ServerID), with Value typed as time.Duration (the selected timeout), not raw bits; repeated decisions draw the next value from the same source.

### 可参考的源码位置

- `util.go:34`：The single hidden non-cryptographic choice site: global math/rand (util.go:18-21 seeds once from crypto) picks a uniform offset in [0,minVal) that determines when election/heartbeat/commit/snapshot timers fire, affecting protocol state and test timing.
- `raft.go:310`：electionTimer := randomTimeout(electionTimeout): the randomized election timeout is the protocol-brief randomness item and drives candidate timing.

### 本次生成接口

- 捕获位置：`random_controller.go / Raft.randomTimeoutFor：Single interception point for every in-scope hidden non-cryptographic draw: follower heartbeat, candidate election, leader commit/replicate, heartbeat interval, and snapshot interval jitter. When the node has a controller installed it performs and records the draw; otherwise it is byte-identical to the original package-level randomTimeout.`
- Pending Store：`random_controller.go / RandomController.choices：Ordered recorded history of final semantic draw results (RandomChoice values), guarded by RandomController.mu so draws from concurrent protocol goroutines are serialized in draw order.`
- 公开入口：`random_controller.go / NewRandomController：Externally callable constructor: NewRandomController(seed int64, owner ServerID) *RandomController creates a deterministic, per-owner controller to be installed through Config.Random before NewRaft starts the node's goroutines.`
- 公开入口：`random_controller.go / RandomController.Choices：Thread-safe, side-effect-free accessor returning the ordered, deep-copied history of recorded protocol draws ([]RandomChoice with Name, Owner ServerID, Value time.Duration).`

### 使用与范围

- 生产路径：Default production behavior unchanged: when Config.Random is nil, Raft.randomTimeoutFor uses the same global math/rand draw and the same time.After arming as the original randomTimeout, so no controller is consulted and no history is recorded. Controlled mode: Config.Random set before NewRaft; all in-scope draws are routed through the controller while the target's legal domain [minVal, 2*minVal), timer arming, and production algorithm are preserved.
- 测试路径：In-package focused tests only: TestRandomControllerDeterminism (same seed and draw order reproduce identical sequences, jitter and values stay inside the legal domain, repeated decisions vary, Choices returns deep copies) and TestRandomControllerNodeDraws (a Config-installed controller on a real NewRaft node records follower heartbeat and snapshot draws with the correct Owner, stable names, and in-domain values).
- 缓存实例引用：One controller per node: the consumer creates it with NewRandomController(seed, ServerID) and installs it via Config.Random; NewRaft binds it to the node's unexported Raft.random field before goroutine launch, and every draw of that node routes through that same instance for the node's lifetime. A restart (fresh NewRaft with the same Config.Random) re-binds the same controller instance and its history, so the reference is stable and reusable across lifecycle changes.
- 目标绑定方式：Not a message-target capability; ownership binding is explicit and concrete instead. Each controller is constructed for one target-native owner (ServerID) and every recorded RandomChoice carries that Owner field; the node hook resolves its own controller from the Raft instance bound at construction, so a choice is always unambiguously attributable to its node.
- 缓存变化与失败语义：Every protocol draw appends one RandomChoice to the ordered history and advances the deterministic source; Choices() is side-effect-free; there is no eviction, Drop, or Clear, and the history only grows. Repeated decisions always consume the next value from the same source, so values keep varying (verified by test); a new controller with a new seed starts a fresh empty history. Installation itself records nothing.
- 复制策略：RandomChoice is a plain value type (string name, ServerID owner, time.Duration value); Choices() allocates a fresh slice and copies the elements, so the returned history never aliases the controller's internal history and mutating it cannot affect later calls. Each recorded Value is the final semantic duration minVal+extra (in [minVal, 2*minVal)), not raw random bits; the internal draw consumes one value from the seeded source per decision.
- All four Agent 1 execution paths are routed through the same controller-owned hook; the capability has a single ownership/completion model (constructor + Config install + node hook), so no separate facade route applies.
- The randomTimeoutFor replacement is a disclosed core_hook: it touches raft.go, replication.go, and snapshot.go but is no-op-by-default and preserves the original algorithm, legal domain, timer arming, and production defaults; no protocol, persistence, state-transition, or ordering semantics changed, so INVASIVE_REDISCOVERED does not apply.
- RandomChoice.Value uses time.Duration, the concrete target-native type of the selected timer durations (TargetRandomValue type slot); RandomChoice.Owner uses ServerID, the target's concrete node-ID type.
- Determinism guarantee: same seed and same draw order per controller reproduce the same sequence; draw order across separate goroutines of one node is whatever the protocol makes (serialized by the controller mutex). Crypto randomness (generateUUID/newSeed in util.go) and the fuzzy/ subdirectory generators are excluded as out of scope.
- Installation boundary is satisfied externally: Config.Random is bound in NewRaft before the goroutines at api.go start, so an external consumer has no uncontrolled first draw; the package-level randomTimeout remains only for util_test.go and is no longer used by production code.
- Restart re-binds the same controller: a fresh NewRaft with the same Config.Random keeps the recorded history and deterministic source usable across lifecycle changes.
- Public surface also includes Config.Random (public wiring field) and the RandomChoice type and five choice-name constants; no other target file behavior was modified.

### 已覆盖路径

- node_follower_loop
- node_candidate_loop
- node_replication_goroutines
- node_snapshot_loop

### 实际实现方式

- dependency injection: new public Config.Random *RandomController field, consumed by NewRaft and bound to Raft.random before the node's goroutines start (api.go)
- core hook (default-disabled, semantics-preserving): new method Raft.randomTimeoutFor(name, minVal) replaces the 8 randomTimeout call sites (raft.go x5: follower heartbeat x2, candidate election x3; replication.go x3: commit timeout x2, heartbeat interval x1; snapshot.go x1), with the no-controller path identical to the original
- constructor: NewRandomController(seed int64, owner ServerID) *RandomController
- typed accessor: RandomController.Choices() []RandomChoice returning deep-copied final semantic values
- stable semantic name constants: RandomChoiceElectionTimeout, RandomChoiceHeartbeatTimeout, RandomChoiceCommitTimeout, RandomChoiceHeartbeatInterval, RandomChoiceSnapshotInterval

### 修改前已知限制（供对照）

- randomTimeout is called from raft.go, replication.go, snapshot.go with no per-node RNG; per-node control requires a no-op-by-default core hook routing draws through the node (e.g., a Random source field on Config or Raft), disclosed as a core hook.
- Installation must happen via constructor/Config before NewRaft launches goroutines (api.go:622-624); the unexported skipStartup (config.go:243-244) is not an external installation point.
- Choices must record stable semantic names (election_timeout, heartbeat_timeout, commit_timeout, heartbeat_interval, snapshot_interval) with typed time.Duration values and per-node ownership (ServerID) or a one-owner controller.
- Excluded: crypto/rand UUID generation (util.go:59-71), newSeed (util.go:25-31), and fuzzy/ subdirectory test generators (out of boundary).

## 生命周期控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Same system boundary: the Raft instance, its goroutines and state, the Transport (InmemTransport in boundary), observer/future mechanisms, and module in-memory stores/snapshots.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：Only Raft.Shutdown()/NewRaft exist; there is no LifecycleController, no Pause/Resume, no Crash primitive, and no ErrLifecycleUnsupported, so the fixed five-operation surface must be added.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- normal_stop: LifecycleController.Stop(node) -> Raft.Shutdown() (api.go:1012) -> shutdownCh closed -> shutdownFuture.Error() waits routinesGroup (future.go:171-179) -> WithClose transport closed
- crash: LifecycleController.Crash(node) -> Raft.Shutdown() as abrupt stop without protocol-state flush, drop instance; durable stores (LogStore/StableStore/SnapshotStore) retain durable state
- restart: LifecycleController.Restart(node) -> NewRaft(conf, fsm, logs, stable, snaps, trans) (api.go:500) -> restoreSnapshot (api.go:631) and processConfigurationLogEntry replay
- pause_resume: LifecycleController.Pause/Resume(node) -> new narrow no-op-by-default pause gate in runFollower/runCandidate/leaderLoop selects (core_hook, proposed)

### Analyzer 建议（修改前）

- Add LifecycleController, NewLifecycleController(...) with Pause(node), Resume(node), Stop(node), Crash(node), Restart(node) error and ErrLifecycleUnsupported in a new file; Stop/Crash/Restart are facades over Raft.Shutdown()/NewRaft (facade_only), with Crash additionally joining untracked goroutines and Restart rewiring transports and re-registering the node with Message/Time/Random controllers.
- Add a narrow no-op-by-default paused flag (core_hook) consulted by runFollower/runCandidate/leaderLoop and the replication goroutines so Pause blocks message handling and timer actions without changing protocol semantics.
- Crash(node) discards the instance (volatile state) and retains only durable store contents; Restart(node) records whether the node was stopped or crashed and constructs a fresh runtime with NewRaft on the same identity/stores.

### 目标已有入口

- `Raft.Shutdown`
- `NewRaft`

### 本次生成接口

- 捕获位置：`lifecycle_control.go / Raft.waitWhilePaused：Default-disabled pause gate consulted at the top of every protocol loop (main loops, replication/heartbeat/pipeline, FSM applier, snapshot loop); LifecycleController.Pause/Resume flip it via setLifecyclePaused and the boundary is acknowledged through pauseNotifyCh/pausedAckCh.`
- Pending Store：`lifecycle_control.go / LifecycleController：managedNode registry (map[ServerID]*managedNode guarded by mu): each entry holds the live runtime binding, the construction parameters captured at Register (Config value copy, FSM, LogStore, StableStore, SnapshotStore, Transport), and the recorded LifecycleStatus.`
- 公开入口：`lifecycle_control.go / NewLifecycleController：Externally callable constructor; optionally pre-registers running nodes (variadic *Raft).`
- 公开入口：`lifecycle_control.go / LifecycleController.Pause：Pause(node ServerID) error: blocks every protocol loop of the node through the default-disabled pause gate and waits until the main loop acknowledges the pause boundary, so message handling, node time progress, and protocol output stop while the same runtime and volatile state are retained.`
- 公开入口：`lifecycle_control.go / LifecycleController.Resume：Resume(node ServerID) error: unblocks the same runtime after Pause and continues it.`
- 公开入口：`lifecycle_control.go / LifecycleController.Stop：Stop(node ServerID) error: normal shutdown through Raft.Shutdown() + shutdownFuture.Error(); waits for every tracked protocol goroutine and every auxiliary goroutine, discards the runtime binding, records LifecycleStopped.`
- 公开入口：`lifecycle_control.go / LifecycleController.Crash：Crash(node ServerID) error: abrupt stop through the target's not-graceful Shutdown primitive (no extra protocol-state flush); joins all tracked and auxiliary goroutines so no old execution context survives, discards the runtime binding, records LifecycleCrashed, retains only durable store state.`
- 公开入口：`lifecycle_control.go / LifecycleController.Restart：Restart(node ServerID) error: rebuilds a fresh runtime through NewRaft with the registered identity, Config, FSM, durable stores, and transport (a fresh ControlledTransport wrapper in controlled deployments, with pending entries re-bound to it); replaces the binding; only valid from stopped or crashed.`
- 公开入口：`lifecycle_control.go / LifecycleController.Register：Register(node *Raft) error: binds a node and captures construction parameters needed by Restart; re-registering replaces the binding; returns an error for a nil node or a node without a stored configuration (never panics).`
- 公开入口：`lifecycle_control.go / LifecycleController.Raft：Raft(id ServerID) *Raft: returns the currently bound runtime (nil after Stop/Crash, the fresh runtime after Restart).`
- 公开入口：`lifecycle_control.go / LifecycleController.Status：Status(id ServerID) (LifecycleStatus, error): recorded lifecycle state (running, paused, stopped, crashed).`
- 公开入口：`lifecycle_control.go / ErrLifecycleUnsupported：Exported sentinel error, classifiable with errors.Is, for an operation that cannot be implemented without core semantic changes; no current lifecycle operation requires it.`
- 公开入口：`lifecycle_control.go / LifecycleStatus：Typed status enum with String(); concrete node identity is ServerID.`

### 使用与范围

- 生产路径：Unchanged when no controller is installed: nodes run exactly as before. The pause gate is inert (paused=false, only an atomic load per loop iteration), the auxiliary goroutines behave exactly as the original plain-go goroutines except that they are joined on shutdown, and Stop/Crash/Restart are reachable only through the LifecycleController. The controller is inactive by default; registration never alters node behavior.
- 测试路径：Focused tests in lifecycle_control_test.go: pause blocks protocol progress (single node stays Follower with commit index 0 while paused and reaches Leader after Resume), pause blocks Apply on a leader until Resume, pause stops protocol output (a paused leader stops heartbeats so the follower starts an election), pause blocks inbound message handling (a paused follower does not process injected AppendEntries - commit index does not advance and the leader's Apply does not complete - and recovers after Resume), Stop+Restart yields a fresh runtime that re-elects itself while the old runtime stays Shutdown, Crash+Restart preserves term and durable log, Crash completes while a leadership transfer is in flight in a controlled deployment and the captured TimeoutNow entry survives, Restart keeps a pre-crash pending message injectable through the re-bound fresh wrapper (TestLifecycleControllerRestartKeepsPendingInjectible), error paths and register-replace semantics (including nil-node and no-stored-config errors), ErrLifecycleUnsupported errors.Is classification, and a 3-node Stop/Restart/rejoin test with transport re-Connect. Cross-capability: TestTimeControllerSkipsPausedAndStoppedNodes verifies the clock-level step exclusion; TestMessageControllerDropAndInjectPreserveOrder and TestMessageControllerClosedOwnerRebind verify the order-preserving cache and re-bound ownership the lifecycle interaction relies on.
- 缓存实例引用：One registry entry per concrete ServerID; entries remain stable across lifecycle operations; the runtime binding is replaced on Restart and nil after Stop/Crash.
- 目标绑定方式：Restart resolves the registered ServerID entry and validates its recorded status (stopped or crashed) before rebuilding; the fresh runtime is bound to the same identity, configuration, and durable stores through NewRaft (the target's normal recovery constructor), the old runtime binding is replaced, and in controlled deployments a fresh ControlledTransport wrapper over the same underlying transport and MessageController is created with every pending entry re-bound to it.
- 缓存变化与失败语义：Node registry keyed by ServerID: Register binds or replaces an entry; Stop and Crash discard the runtime binding (Raft(id) returns nil) while retaining construction parameters; Restart re-binds the fresh runtime and re-binds pending MessageController entries owned by the old wrapper to the fresh wrapper; Status records the lifecycle state; Pause/Resume flip the recorded status without touching the binding; all operations on unknown IDs return errors and leave the registry unchanged; pending MessageController entries are never cleared or reordered by lifecycle operations.
- 复制策略：Register captures a value copy of the node's Config (no slices or maps; Clock and Random controller references are preserved so determinism and time control survive Restart) plus references to the caller-owned FSM, LogStore, StableStore, SnapshotStore, and Transport; Restart rebuilds from these without aliasing the live runtime and re-creates a ControlledTransport wrapper when the registered transport is one.
- Review blocking issue 1 resolved: MessageController.removeLocked now deletes with an order-preserving slice splice (append(c.pending[:i], c.pending[i+1:]...)) instead of a swap-with-last delete, so Pending preserves controller acceptance order and Drop/Inject never reorder other entries (verified by TestMessageControllerDropAndInjectPreserveOrder)
- Review blocking issue 2 resolved: MessageController.Inject no longer selects on the owner's closedCh (a permanently-ready case after Stop/Crash); it performs one deterministic non-blocking closed-owner check before delivery, and LifecycleController.Restart re-binds pending entries of the closed wrapper to the fresh wrapper via rebindOwner, so post-restart injection of pre-crash pending messages is deterministic and usable (verified by TestLifecycleControllerRestartKeepsPendingInjectible)
- Pause: core_hook - narrow default-disabled pause gate (waitWhilePaused plus pauseNotifyCh boundary cases) in runFollower/runCandidate/leaderLoop (raft.go), replicate/replicateTo/heartbeat/pipelineReplicate (replication.go), runFSM (fsm.go), and runSnapshots (snapshot.go); semantics-preserving while unused; Pause waits for the main loop to acknowledge the boundary; an operation already in flight at Pause time completes first
- Resume: core_hook - closes the pause channel of the same gate and drains stale boundary signals
- Stop: facade_only - wraps the target's normal shutdown (Raft.Shutdown, api.go), waits for all tracked protocol goroutines (routinesGroup) and auxiliary goroutines (auxWG), records LifecycleStopped, and discards the runtime binding
- Crash: facade_only - uses the same target primitive because Raft.Shutdown is documented as not graceful (no extra protocol-state flush); core_hook addition: the formerly untracked plain-go goroutines (leadershipTransfer, its timeout watcher, emitLogStoreMetrics) are now auxGo-tracked with shutdown aborts, and waitAux joins them before Crash returns, so no old execution context can process protocol work, emit protocol output (such as a TimeoutNow request), or mutate volatile state, the application state machine, or durable storage after Crash returns
- Restart: facade_only - rebuilds via NewRaft with the registered construction parameters (the target's normal recovery path); records whether the node was stopped or crashed; post-restart catch-up is left to the protocol and test
- Controller interaction: messages already pending in a MessageController survive lifecycle changes untouched (never cleared or reordered); Inject to a stopped/crashed node fails deterministically (ErrMessageNotAccepted via the closed-owner check, or ErrTargetUnavailable for a disconnected peer) and preserves the entry; after Restart the same handles are injectable again through the re-bound fresh wrapper (TestLifecycleControllerRestartKeepsPendingInjectible)
- Time interaction: paused, stopped, and crashed nodes do not receive TimeController steps - NewRaft wraps the configured virtual clock with a nodeClock attributing timers to the node, and virtualClock.advance holds paused-node timers until resume and discards timers of stopped/crashed runtimes when they come due (time_controller.go, verified by TestTimeControllerSkipsPausedAndStoppedNodes)
- After Stop/Crash the target's shutdownFuture closes WithClose transports (InmemTransport.Close -> DisconnectAll wipes in-memory routes), so consumers must re-Connect in-memory routes after Restart (shown in the rejoin test and usage example)
- ErrLifecycleUnsupported is exported and errors.Is-classifiable; no lifecycle operation in this target required core semantic changes, so no method currently returns it
- Remaining disclosed limitation: transport-level RPC delivery deadlines in the controlled transport (waitRPC/Inject send timeouts) and MessageController enqueue timeouts remain wall-clock based; they are RPC delivery deadlines, not protocol timers, and never gate protocol state transitions
- Remaining disclosed limitation: TimeController.nodes bookkeeping is not automatically re-bound on LifecycleController.Restart; behavior is unaffected because Advance is clock-driven and the fresh runtime inherits Config.Clock/Config.Random; re-registering the fresh runtime with the TimeController returns a duplicate-ID error (bookkeeping only)
- LifecycleController.Register captures a value copy of Config; Clock and Random controller references are preserved across Restart, but post-registration Config mutations are not propagated until re-registration

### 已覆盖路径

- pause_resume: LifecycleController.Pause -> default-disabled pause gate (core_hook) in runFollower/runCandidate/leaderLoop (raft.go), replicate/replicateTo/heartbeat/pipelineReplicate (replication.go), runFSM (fsm.go), and runSnapshots (snapshot.go) -> all loops block before selecting (no RPC handling, no protocol timer action, no leadership/commit/apply/snapshot decision, no outbound AppendEntries/heartbeat/pipeline/snapshot/TimeoutNow) -> Resume continues the same runtime and volatile state
- normal_stop: LifecycleController.Stop -> Raft.Shutdown() (api.go) -> shutdownCh closed -> shutdownFuture.Error() waits for routinesGroup and closes WithClose transports -> r.waitAux() joins the auxiliary goroutines (leadership transfer, transfer timeout watcher, log-store metrics emitter) -> runtime binding discarded -> status LifecycleStopped
- crash: LifecycleController.Crash -> same not-graceful Shutdown primitive (no extra protocol-state flush) -> routinesGroup and auxWG fully joined before return (leadershipTransfer, its timeout watcher, and emitLogStoreMetrics are auxGo-tracked with shutdown aborts at every blocking point) -> runtime binding discarded -> caller-owned durable stores (term/log/snapshot/config) retained -> status LifecycleCrashed
- restart: LifecycleController.Restart -> NewRaft with registered conf/fsm/logs/stable/snaps/trans -> restoreSnapshot and configuration log replay (normal recovery) -> fresh runtime bound and old runtime replaced; stopped-vs-crashed recorded; fresh ControlledTransport wrapper re-created in controlled deployments; Config.Clock/Config.Random references preserved so time and randomness control ownership remains usable
- lifecycle_message_controller_interaction: messages already pending in a MessageController survive Stop/Crash untouched; Restart re-binds every pending entry of the old closed wrapper to the fresh wrapper (MessageController.rebindOwner), so pre-crash handles remain injectable after restart through the live peer's normal ingress and are invalidated only on confirmed acceptance (TestLifecycleControllerRestartKeepsPendingInjectible)
- lifecycle_inject_unavailable: Inject into a stopped or crashed node fails deterministically - the closed-owner check in MessageController.Inject (non-blocking, before delivery) returns ErrMessageNotAccepted and preserves the entry, and a disconnected peer yields ErrTargetUnavailable with the entry preserved (verified in lifecycle and message controller tests)
- lifecycle_time_controller_interaction: paused, stopped, and crashed nodes do not receive TimeController steps - NewRaft wraps the configured virtual clock with a nodeClock attributing timers to the node, and virtualClock.advance holds paused-node timers until resume and discards timers of stopped/crashed runtimes when they come due (time_controller.go, TestTimeControllerSkipsPausedAndStoppedNodes)

### 未覆盖路径

- strict_crash_context_bounded: Crash while a leadership transfer is in flight waits for the auxGo-tracked transfer goroutines; the transfer goroutine can remain blocked in the TimeoutNow transport call until the transport-level timeout resolves (ControlledTransport uses 10x the base timeout for TimeoutNow/InstallSnapshot), so Crash is bounded by that timeout rather than instantaneous; the goroutine never mutates durable storage or the FSM, and every other blocking point aborts on shutdown signals
- time_controller_registry_restart: TimeController.nodes is bookkeeping-only and is not automatically re-bound by LifecycleController.Restart; a subsequent Register of the fresh runtime returns a duplicate-ID error (verified behavior of TestTimeControllerRegister); Advance is unaffected because it is driven by the shared virtual clock and NewRaft re-wraps Config.Clock with a fresh nodeClock for the fresh runtime
- pause_boundary_ack: Pause waits for the main loop's pause acknowledgment; the replication/FSM/snapshot goroutines reach their gate at their next loop boundary, so an operation already in flight at the time of the Pause call completes first (documented quiescence scope)
- per_node_time_drift: the shared-clock model advances all running nodes together; per-node drift or separate advancement is out of v0 scope (paused, stopped, and crashed nodes are excluded at the clock level instead)

### 实际实现方式

- facade over Raft.Shutdown()/shutdownFuture for Stop and Crash (the target's own normal/abrupt stop primitive, documented as not graceful, so no extra protocol-state flush)
- facade over NewRaft for Restart using construction parameters captured at Register (identity, Config value copy, FSM, LogStore, StableStore, SnapshotStore, Transport)
- default-disabled core hook: pause-gate fields on Raft (paused atomic.Bool, pausedMu, pausedCh, pausedAckCh, pauseNotifyCh) plus waitWhilePaused checks and pauseNotifyCh boundary cases inserted in runFollower, runCandidate, leaderLoop, replicate, replicateTo, heartbeat, pipelineReplicate, runFSM, and runSnapshots; inert while unused
- synchronous pause boundary: Pause wakes the idle main loop through pauseNotifyCh and waits for its acknowledgment on pausedAckCh, so the node's main loop is quiescent when Pause returns and events enqueued after Pause are never processed
- core hook for crash completeness: auxiliary goroutines (leadershipTransfer, its timeout watcher, emitLogStoreMetrics) are tracked with auxGo/auxWG (state.go) and every blocking point they can reach is aborted by shutdownCh/leftLeaderLoop/stopCh or the transport close; LifecycleController.terminate calls r.waitAux() after Shutdown().Error() so no abandoned execution context survives Stop or Crash
- controlled-transport integration: Restart creates a fresh ControlledTransport wrapper over the same underlying InmemTransport and MessageController and re-binds every pending entry owned by the closed wrapper to it (MessageController.rebindOwner), so message capture/injection ownership remains usable after restart
- defensive registration: LifecycleController.Register now uses a checked type assertion on the stored Config and returns an error instead of panicking for a zero-value or manually constructed *Raft
- typed accessors Raft(id) and Status(id) so consumers can reach the fresh runtime and recorded lifecycle state

### 修改前已知限制（供对照）

- Pause implemented via controllers only works while Message/Time controllers are installed; for uncontrolled nodes a core pause gate is required (disclosed core_hook).
- Crash-as-Shutdown closes the transport (future.go:176-178); Restart must reconnect InmemTransport peers (InmemTransport.Close -> DisconnectAll, inmem_transport.go:254-257).
- Plain-go goroutines (raft.go:499, 725, 783) are not joined by waitShutdown; a strict Crash must verify they exited before returning.
- Restart does not implement protocol catch-up beyond what NewRaft's normal recovery provides (per contract, catch-up is out of seam scope).

## 状态观察

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Same system boundary: public Raft state views, observer mechanism, and typed getters.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The existing typed getters and observer mechanism fully cover role, term, commit/applied index, configuration, leadership, and last-contact observation with thread-safe reads and cloned configuration snapshots; no new Observe() accessor is needed.

### Analyzer 发现的实现路径（修改前）

- per_node_state_view: Raft.State (atomic, state.go:79-87) / Stats() map (api.go:1160) / CurrentTerm / LastIndex / CommitIndex / AppliedIndex
- leadership_view: Raft.LeaderWithID (api.go:796) / Raft.LeaderCh (api.go:1117)
- configuration_view: Raft.GetConfiguration -> configurationsFuture with cloned configuration (raft.go:200-201, configuration.go:164-167)
- event_view: RegisterObserver/NewObserver -> Observation channel with typed Data (observer.go:11-21, 87-94)

### Analyzer 建议（修改前）

- No target change required; tests should use State/Stats/GetConfiguration/LeaderWithID and the Observer API directly and treat each read as an independent per-node snapshot.

### 目标已有入口

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

### 当前限制

- No simultaneous cross-node snapshot: each getter is individually consistent but a test reading several nodes or several getters may observe temporally inconsistent values; disclose per-node snapshot semantics.
- Stats() returns strings and mixes committed indices with fsm_pending; it is safe but less typed than State()/CurrentTerm()/CommitIndex().
- Raft.LastContact returns a wall-clock time and is meaningful only for followers.
- GetConfiguration may reflect an uncommitted latest configuration (api.go:895-903); completion meaning must be documented by the test.

## 外部输入

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Public Raft API and protocol state loops, Transport abstraction, InmemTransport, observer and future mechanisms, module-provided in-memory stores and snapshots, and package-provided in-process testing support are inside; real TCP/network transports, external durable stores, application FSM semantics, process supervision, and the raft-compat/fuzzy/bench subdirectories are outside.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The unmodified public API already exposes all ordinary workload entrypoints with typed futures and documented completion semantics; this discovery-only capability needs no target change.

### Analyzer 发现的实现路径（修改前）

- proposal: Raft.Apply/ApplyLog -> applyCh -> leader dispatchLogs -> replicate to quorum -> commit -> runFSM fsm.Apply -> ApplyFuture.Error/Response
- membership_change: Raft.AddVoter/AddNonvoter/RemoveServer/DemoteVoter -> requestConfigChange -> configurationChangeCh -> appendConfigurationEntry -> committed configuration -> IndexFuture

### Analyzer 建议（修改前）

- No target code change required; optionally add a doc example to the package docs for Apply and AddVoter in-process test usage.

### 目标已有入口

- `Raft.Apply`
- `Raft.ApplyLog`
- `Raft.AddVoter`
- `Raft.AddNonvoter`
- `Raft.RemoveServer`
- `Raft.DemoteVoter`

### 当前限制

- Deprecated protocol<3 entrypoints AddPeer/RemovePeer (api.go:908, api.go:926) also exist but are deprecated and return ErrUnsupportedProtocol for ProtocolVersion >= 3.
- LeadershipTransfer/LeadershipTransferToServer (api.go:1261/1276), Barrier (api.go:859), VerifyLeader (api.go:883), BootstrapCluster (api.go:769), Restore (api.go:1056), Snapshot (api.go:1030), GetConfiguration (api.go:897) and ReloadConfig (api.go:717) are intentionally excluded per spec (administration, barrier, bootstrap, restore, status/configuration query).
- Apply requires the node to be leader; preconditions and error paths (ErrNotLeader, ErrLeadershipLost, ErrEnqueueTimeout, ErrRaftShutdown) are documented at api.go:804-818.

## 独立 Reviewer 结论

- 总体结论：`PASS`

### 非阻塞剩余风险

- Concurrent Drop or Clear during an already-in-flight Inject is not serialized against delivery: the injecting flag guards Inject-vs-Inject, but Drop/Clear remove the entry without checking injecting, so a message whose delivery has begun can still be enqueued after it was concurrently removed. This does not corrupt cache state or reorder entries, but the 'remove without delivering' guarantee is best-effort under that specific race.
- The awaitResponse goroutine launched after a request is accepted can linger if the target node stops/crashes without responding while the source transport remains open; it only exits on the source transport close. This has no protocol impact and only affects controller bookkeeping.
- Pause acknowledgment is sent by any gated loop (main, replication, FSM, snapshot), so Pause's quiescence guarantee is best-effort: work already in flight can still complete at the pause boundary, as documented.
- Wall-clock timeouts remain in ControlledTransport.waitRPC, the controlled pipeline, and Inject's enqueue; these are RPC delivery deadlines, not protocol timers, and are disclosed as outside the time-control scope.
- TimeController.Register is bookkeeping-only and is not automatically re-bound by LifecycleController.Restart (Advance is clock-driven and the fresh runtime inherits Config.Clock); a re-register after restart returns a duplicate-ID error.
