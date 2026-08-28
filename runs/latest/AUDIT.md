# etcd-raft 测试接口审计报告

> [!WARNING]
> 本次运行未完成，以下内容仅反映中断前已经产生的阶段性结果。
> 生成接口、调用示例和 Reviewer 结论可能缺失，不得作为最终使用说明。

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
Analyzer 内容描述修改前状态；生成接口和 Reviewer 内容描述候选修改后状态。
机器可读细节以`capability-report.json`、`interface-report.json`、`review-report.json`为准。

## 消息捕获

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Protocol output points inside the library: Ready().Messages for RawNode and Node, and the rafttest InteractionEnv queue env.Messages plus per-node AppendWork/ApplyWork queues for async-storage messages. The real network send is outside; rafttest's internal network channels are an unexported in-package transport harness.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：The rafttest env.Messages queue is a strong capture primitive (explicit activation, public enumeration, no auto-continuation, consume/drop via DeliverMsgs), but it exposes only bulk per-recipient removal: two duplicate messages to the same recipient cannot be individually addressed, there are no stable per-instance references, and there is no clear-all operation; the RawNode/Node paths have no retained cache at all.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- Synchronous RawNode path: readyWithoutAccept exposes r.msgs as Ready.Messages; messages do not auto-continue (the app must send them), but the batch is one-shot: no retained cache, no enumeration over time, no per-instance operations.
- Asynchronous Node path: node.run publishes Ready on readyc; the app consumes the channel; same one-shot semantics.
- rafttest InteractionEnv path: ProcessReady appends non-local Ready messages to env.Messages (order-preserving public slice); messages never auto-continue; DeliverMsgs consumes (delivers) or removes (drops) them per recipient and optional type; stabilization loops drive delivery explicitly.
- Async-storage-writes path inside the env: MsgStorageAppend/MsgStorageApply are diverted to per-node AppendWork/ApplyWork queues and consumed one-at-a-time by ProcessAppendThread/ProcessApplyThread, whose responses are appended back into env.Messages.
- Internal network harness path (rafttest/node.go + network.go): send() places messages into per-recipient channel queues consumed by node goroutines; unexported, in-package tests only.

### Analyzer 建议（修改前）

- Add per-instance operations to InteractionEnv on top of the authoritative env.Messages: e.g. a Take(handle)/Drop(handle)/Clear() facade where enumeration returns stable handles (validated against the current queue) so one concrete duplicate instance can be removed or delivered.
- Optionally add a capture hook or test cache to RawNode (e.g. an outbound-message sink option on Config) so the synchronous RawNode path gets a retained, test-controlled cache instead of a one-shot Ready.
- Keep env.Messages as the single authoritative cache; do not introduce a parallel store.

### 目标已有入口

- `RawNode.Ready() / readyWithoutAccept() (one-shot batch)`
- `Node.Ready() <-chan Ready (channel handoff)`
- `rafttest InteractionEnv.ProcessReady(idx) (captures into env.Messages)`
- `rafttest InteractionEnv.DeliverMsgs(typ, recipients...) (consume/drop from env.Messages)`
- `rafttest InteractionEnv.Messages (public enumeration)`
- `rafttest ProcessAppendThread/ProcessApplyThread (consume AppendWork/ApplyWork FIFO)`

### 本次生成接口

- 捕获位置：`rafttest/interaction_env_handler_process_ready.go / InteractionEnv.ProcessReady：Capture activation point: non-local Ready messages are appended to env.Messages (appendMessages); local MsgStorage* messages continue to per-node AppendWork/ApplyWork queues.`
- Pending Store：`rafttest/interaction_env.go / InteractionEnv.Messages：Authoritative in-flight message cache, extended with lock-step per-entry ids (msgIDs, nextMsgID) backing MessageHandle.`
- 调用入口：`rafttest/interaction_env_handle.go / InteractionEnv.EnumerateMessages：Primary enumeration entrypoint of the capture facade.`

### 使用与范围

- 生产路径：Core protocol unchanged: no changes to raft.go, node.go, rawnode.go, storage, or message semantics. All changes live in the rafttest test-support package (public test facade) and its tests.
- 测试路径：Public rafttest InteractionEnv facade (NewInteractionEnv + AddNodes + ProcessReady activation); the new per-instance operations are regular public methods, usable by any external consumer that imports go.etcd.io/raft/v3/rafttest.
- 缓存实例引用：MessageHandle is an opaque struct with unexported fields (env pointer plus a monotonically increasing per-env id assigned at append time). It is obtained only from EnumerateMessages, cannot be forged by tests, and continues to denote the same concrete cache instance (including among equal-valued duplicates) until that instance is consumed by TakeMessage/InjectMessage, removed by DropMessage/ClearMessages, or delivered/dropped by DeliverMsgs. Scope: the pending store of one InteractionEnv instance.
- 缓存变化与失败语义：EnumerateMessages: read-only, cache unchanged, returns deep copies plus handles. TakeMessage: removes exactly the referenced instance from env.Messages (and its id); returns a deep copy; stale handle returns ok=false and mutates nothing. DropMessage: removes exactly the referenced instance without delivery; stale handle returns false. ClearMessages: removes all instances and returns the count; all handles become invalid. DeliverMsgs: bulk removal per recipient/type (existing semantics), handles of handled messages become invalid. Successful injection: see message_injection.cache_effects.
- 可选消息 ID 范围：pending_store_instance
- 复制策略：Deep clone of every mutable field (Context, Entries[].Data, Snapshot.Data, Responses recursively) for all snapshots returned by EnumerateMessages and TakeMessage; the cache itself stores the original values as before.
- All in-tree env.Messages mutations were rewired through handle-aware helpers (appendMessages, removeIndex, splitMsgsWithIDs, ClearMessages), so outstanding MessageHandles stay consistent with every existing mutation path: ProcessReady, SendSnapshot, ProcessAppendThread, ProcessApplyThread, DeliverMsgs.
- env.Messages remains the single authoritative cache; msgIDs is per-entry metadata kept in lock-step by the helpers. Direct external splicing of the public env.Messages field is not performed by any in-tree consumer and can invalidate outstanding handles; the new facade methods are the supported mutation surface.
- EnumerateMessages and TakeMessage return deep copies (Context, Entries[].Data, Snapshot.Data, Responses cloned recursively); mutating a returned snapshot cannot affect the cache or the raft state machine.
- The pre-existing documented Ready contract (Ready.Messages slices share backing with raft state) is unchanged for the existing bulk paths; the new enumeration API does not expose such aliases.
- Duplicate equal-valued messages receive distinct handles and remain separately controllable.
- The env is single-threaded and all operations are synchronous; no wait-for-quiescence or acknowledgement mechanism was invented.
- Capture activation is ProcessReady(idx); the environment keeps captured messages until a declared test operation (TakeMessage, DropMessage, InjectMessage, DeliverMsgs, ClearMessages) consumes or removes them.

### 已覆盖路径

- rafttest InteractionEnv capture path: env.ProcessReady(idx) diverts non-local Ready output into the authoritative env.Messages cache (via appendMessages) and nothing auto-continues; tests enumerate, take, drop, clear, and inject cached instances through stable handles; the facade is publicly importable (go.etcd.io/raft/v3/rafttest).
- Async-storage-writes responses path: ProcessAppendThread/ProcessApplyThread responses enter the same env.Messages cache with stable handles, so messages produced by storage-thread simulation are controllable exactly like peer messages.
- Cache-side synthesis path: SendSnapshot enqueues a synthesized MsgSnap into the same authoritative cache with a stable handle, then the message can be enumerated, taken, dropped, or injected per instance.

### 未覆盖路径

- RawNode.Ready / readyWithoutAccept one-shot batch path: Ready hands out r.msgs as a single batch and Advance clears it; there is no retained test cache, and adding one would change the Ready output/Advance contract on the production path (INVASIVE).
- Node.Ready channel path: one-shot channel handoff with no retained cache; same invasive constraint as RawNode.Ready.
- Internal network harness (rafttest/node.go + network.go): unexported in-package transport simulation with per-recipient channel queues and no per-instance operations; it simulates the real network send, which is outside the declared capture boundary.

### 实际实现方式

- Extended the existing rafttest InteractionEnv facade: kept env.Messages as the single authoritative cache and added opaque per-instance MessageHandle metadata (msgIDs kept in lock-step).
- Added public per-instance operations EnumerateMessages, TakeMessage, DropMessage, ClearMessages, and InjectMessage on InteractionEnv (new file rafttest/interaction_env_handle.go).
- Rewired every existing cache mutation (ProcessReady, SendSnapshot, ProcessAppendThread, ProcessApplyThread, DeliverMsgs) through handle-aware helpers so handles stay consistent with all mutation paths; DeliverMsgs now uses splitMsgsWithIDs.
- Returned snapshots are deep copies, satisfying snapshot safety without changing the pre-existing Ready contract.
- Added same-package focused tests (rafttest/interaction_env_handle_test.go) covering capture, exact-instance take/drop, duplicates, injection, error/cache-effect contract, and snapshot safety.

### 修改前已知限制（供对照）

- Real network sends are outside the boundary; the internal rafttest network (rafttest/node.go, network.go) is an unexported in-package harness.
- env.Messages entries are value copies of pb.Message but share slice backing (Entries, Context) with the Ready/raft state; mutation is unsafe per the documented read-only Ready contract.
- The datadriven env's AppendWork/ApplyWork queues are FIFO-only (front removal), also lacking exact-instance operations.

## 消息注入

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Normal protocol input boundaries inside the library: RawNode.Step (synchronous) and Node.Step (asynchronous via recvc), and the rafttest env's cache-linked DeliverMsgs/SendSnapshot. Direct protocol-state mutation and real network ingress are outside.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：DeliverMsgs already operates on the same authoritative cache used by capture, delivers through the normal RawNode.Step boundary with real target-object binding and synchronous semantics, and SendSnapshot shows cache-side injection; but the facade selects per-recipient bulk sets rather than one exact cached instance, and the RawNode/Node paths expose only raw ingress primitives without cache linkage.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- rafttest env path: DeliverMsgs takes messages out of env.Messages (the same cache used by capture), resolves toIdx = msg.To - 1, and calls env.Nodes[toIdx].Step(msg) synchronously; sender, receiver and content are unchanged; errors are reported synchronously.
- rafttest SendSnapshot path: a synthesized MsgSnap is appended to env.Messages and later delivered through DeliverMsgs to the target RawNode.
- Synchronous RawNode path: RawNode.Step validates local/response-message rules and calls raft.Step directly; no cache linkage exists.
- Asynchronous Node path: Node.Step enqueues on recvc; the run loop steps it, returning only channel-accept errors (ctx.Err/ErrStopped); no cache linkage exists.

### Analyzer 建议（修改前）

- Extend DeliverMsgs (or add env.TakeMessage(handle) + env.Nodes[to].Step) with per-instance handles returned by cache enumeration so one concrete cached duplicate can be injected; handles must stay bound to the instance until consumption.
- Optionally add an env.Inject(handle) combined operation that documents the cache effect (removal) and synchronous error behavior.
- For the Node path, document that Step is an async primitive with channel-accept-only errors; a cache-linked facade would need a capture cache first.

### 目标已有入口

- `rafttest InteractionEnv.DeliverMsgs(typ, recipients...) (Take+Inject combined)`
- `rafttest InteractionEnv.SendSnapshot(fromIdx, toIdx) (inject synthesized MsgSnap into cache)`
- `RawNode.Step(m pb.Message) (raw ingress primitive)`
- `Node.Step(ctx, m pb.Message) (raw ingress primitive, async delivery)`

### 本次生成接口

- 捕获位置：`rafttest/interaction_env_handle.go / InteractionEnv.InjectMessage：Injection consumes from the same authoritative cache (env.Messages) populated by ProcessReady/SendSnapshot/thread responses.`
- Pending Store：`rafttest/interaction_env.go / InteractionEnv.Messages：Authoritative cache shared with message capture; inject removes the referenced instance from it before stepping.`
- 调用入口：`rafttest/interaction_env_handle.go / InteractionEnv.InjectMessage：Primary exact-instance cache-linked injection entrypoint.`

### 使用与范围

- 生产路径：Core protocol unchanged: RawNode.Step is invoked as the pre-existing normal protocol input boundary; no protocol conditions, message content, or destination semantics were modified.
- 测试路径：Public rafttest InteractionEnv facade; InjectMessage is a regular public method callable by any external consumer importing go.etcd.io/raft/v3/rafttest.
- 缓存实例引用：Same MessageHandle as message capture: opaque, per-env unique id, stable until the instance is consumed, removed, or cleared; duplicates remain separately addressable.
- 目标绑定方式：The cached destination is resolved to the real target object using the env's existing node collection: toIdx = int(msg.To - 1), validated against len(env.Nodes) before the message is removed; delivery then calls env.Nodes[toIdx].Step(msg) on the actual RawNode. No caller-supplied target object is needed, and no target ID alone is used as binding.
- 缓存变化与失败语义：Success: the referenced instance is removed from env.Messages and delivered via RawNode.Step; the handle becomes invalid. Synchronous Step error: the instance is already removed from the cache and the error is returned; retry/requeue/loss policy is the test's (documented). Unknown destination (msg.To out of range): error returned, message remains cached. Stale/foreign handle: error returned, nothing removed. DeliverMsgs: bulk removal with delivery or drop; handled handles invalidated. EnumerateMessages/TakeMessage: see message_capture.cache_effects. Unconfirmed asynchronous delivery: not applicable on this path (RawNode.Step is synchronous); the async Node.Step path is uncovered.
- 可选消息 ID 范围：pending_store_instance
- 复制策略：TakeMessage returns a deep copy for inspection; InjectMessage steps the cache's own message value (the instance is removed first, so no alias escapes); enumeration snapshots are deep clones.
- Injection never mutates protocol state directly: all state changes go through RawNode.Step semantics.
- InjectMessage cache/error contract: on success the message is removed from the cache and stepped into the target; on a synchronous Step error the message has already been removed and the error is returned, leaving retry/requeue/loss policy to the test (documented in the method comment); on an unknown destination (msg.To out of the env's node range) an error is returned and the message stays cached; on a stale handle an error is returned and nothing is removed.
- The env path is fully synchronous (RawNode.Step), so InjectMessage never reports confirmed success for an unconfirmed asynchronous send; the async Node.Step path is reported uncovered rather than wrapped with invented semantics.
- Target binding uses the env's existing node indexing (msg.To - 1) validated against len(env.Nodes) before removal, and steps the real env.Nodes[toIdx].RawNode object; a target ID alone is not used as binding.
- Both capture and injection operate on the same authoritative env.Messages cache as one coherent message-control seam (EnumerateMessages/TakeMessage/DropMessage/InjectMessage/ClearMessages).

### 已覆盖路径

- Exact-instance injection path: env.InjectMessage(handle) removes the referenced message from the authoritative env.Messages cache, resolves its cached destination (msg.To) to the real RawNode via env.Nodes[msg.To-1], and delivers it through the normal protocol input boundary RawNode.Step; sender, receiver, and content are preserved; the env path is fully synchronous.
- Bulk injection path: env.DeliverMsgs(typ, recipients...) continues to deliver (or drop) every cached message matching recipient/type through the same cache and the same RawNode.Step boundary; handles of handled messages become invalid.
- Cache-side synthesis path: env.SendSnapshot(fromIdx, toIdx) enqueues a synthesized MsgSnap into the same authoritative cache, which can then be injected exactly via InjectMessage.

### 未覆盖路径

- RawNode.Step and Node.Step raw ingress primitives: they are protocol input primitives on paths without a capture cache; a cache-linked injection facade there would require adding a retained capture cache to RawNode/Node, which changes the Ready output contract (INVASIVE).
- Node.Step asynchronous path: delivery is channel-accept only and protocol processing is asynchronous; without a capture cache no combined wrapper could report confirmed delivery, so this path is reported rather than force-covered.

### 实际实现方式

- Added InjectMessage to the InteractionEnv facade: indexOf validation, destination range validation before removal, removeIndex, then env.Nodes[toIdx].Step (normal RawNode.Step ingress).
- Kept DeliverMsgs as the bulk cache-linked path, rewired through splitMsgsWithIDs so handle metadata stays aligned.
- Documented the exact cache effect for success, synchronous Step error, unknown destination, and stale handle.
- Added focused same-package tests covering injection success (election flow), error contract, and cache effects.

### 修改前已知限制（供对照）

- Node.Step delivery is asynchronous: confirmed success means channel acceptance, and the run loop ignores step errors; a combined wrapper must not claim more.
- Target binding relies on the env's node indexing (msg.To - 1); raw Step paths require the caller to hold the target object.
- Injection does not mutate protocol state directly; all state changes go through raft.Step semantics.

## 时间控制

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Time observed by the raft state machine inside the library: Tick/TickQuiesced on RawNode and Node, and rafttest Tick/tick-election/tick-heartbeat handlers. Wall-clock tickers and sleep delays in the internal network harness (rafttest/node.go, network.go) are transport simulation outside the protocol.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Tick and TickQuiesced are public, deterministic, and directly testable on both RawNode and Node; no coordination wrapper or injectable clock is needed because the state machine never reads wall-clock time.

### Analyzer 发现的实现路径（修改前）

- Synchronous RawNode path: RawNode.Tick() calls r.raft.tick() (tickElection for followers/candidates, tickHeartbeat for leaders), advancing elapsed counters and conditionally stepping MsgHup/MsgBeat/MsgCheckQuorum.
- Asynchronous Node path: Node.Tick() sends to the buffered tickc channel; the run loop calls n.rn.Tick().
- rafttest env path: env.Tick(idx, num) applies num ticks; tick-election/tick-heartbeat apply exactly ElectionTick/HeartbeatTick ticks.

### 目标已有入口

- `RawNode.Tick()`
- `RawNode.TickQuiesced()`
- `Node.Tick()`
- `rafttest InteractionEnv.Tick(idx, num)`
- `rafttest tick-election / tick-heartbeat commands`

### 当前限制

- Election firing still depends on the randomized election timeout; deterministic elections additionally require randomness_control (module-internal setter today).
- The internal harness's real-time ticker/sleep (rafttest/node.go) and network delays (rafttest/network.go) are transport simulation outside the protocol's time model.

## 随机性控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Randomness used by the raft state machine: randomizedElectionTimeout generation in resetRandomizedElectionTimeout. Network-level randomness in the test harness (raftNetwork.rand) is transport simulation and outside the protocol.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：Same-module tests can fix the randomized election timeout (internal setter and the exported test-file setter), but external consumers have no way to seed or inject the randomness source; a complete test-facing interface requires a library-level option or setter.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- Protocol path: resetRandomizedElectionTimeout sets randomizedElectionTimeout = electionTimeout + globalRand.Intn(electionTimeout); globalRand is a locked wrapper over crypto/rand.Reader, reset on every becomeFollower/reset.
- Test-only fix path (module-internal): setRandomizedElectionTimeout / SetRandomizedElectionTimeout overwrite the field directly; rafttest's datadriven command invokes the plumbed function.

### Analyzer 建议（修改前）

- Add a Config option (e.g. RandomizedElectionTimeout int, or an injectable rand source/reader) validated in Config.validate against the legal domain [ElectionTick, 2*ElectionTick-1] (or explicitly document a validated test-only domain), and use it in resetRandomizedElectionTimeout.
- Alternatively, move an exported setter like SetRandomizedElectionTimeout from raft_test.go into a non-test library file so external tests can fix the value.

### 目标已有入口

- `raft.setRandomizedElectionTimeout(r, v) (package-internal)`
- `raft.SetRandomizedElectionTimeout(rn, v) (exported from raft_test.go; test-binary-only)`
- `rafttest set-randomized-election-timeout command (via InteractionOpts.SetRandomizedElectionTimeout, plumbed only by this module's interaction_test.go)`

### 本次生成接口

- 调用入口：`raft.go / Config.RandomizedElectionTimeout：Validated test-configuration option consumed by NewRawNode, StartNode, RestartNode (via newRaft) and by rafttest node creation through InteractionOpts.OnConfig.`

### 使用与范围

- 生产路径：Unchanged when Config.RandomizedElectionTimeout is zero (the default): resetRandomizedElectionTimeout still draws uniformly from [ElectionTick, 2*ElectionTick-1] via the locked crypto/rand-backed globalRand. When the option is set, the draw is replaced by the validated fixed value on every state reset; no protocol condition, message, or persistence semantics change.
- 测试路径：Library-level validated Config option (zero = default random). Same-module tests additionally keep the unvalidated test-file setters and the datadriven rafttest command; the library-facing domain is documented as [ElectionTick, 2*ElectionTick-1].
- Config.validate rejects RandomizedElectionTimeout outside [ElectionTick, 2*ElectionTick-1] with 'randomized election timeout must be in [election tick, 2 * election tick - 1]', so the hook cannot create a timeout the state machine normally considers impossible.
- The fixed value is stored on the raft struct at construction (newRaft) and reused by resetRandomizedElectionTimeout on every becomeFollower/becomeCandidate reset, keeping elections deterministic across term changes and re-elections.
- The default random-draw algorithm and its legal domain are unchanged; only the value source is overridden when the option is non-zero.
- The pre-existing test-file setter SetRandomizedElectionTimeout (raft_test.go) still accepts arbitrary values without validation; it is same-module test support only and is not part of the library-facing interface.
- Focused tests added: raft_randomized_election_timeout_test.go (validation domain, fixed-value stability across resets, default domain, RawNode.Tick determinism) and rafttest/interaction_env_randomized_test.go (OnConfig-based env path). Full module suite (go test ./...) and the build command (go test -run '^$' ./...) pass.

### 已覆盖路径

- Synchronous RawNode path: NewRawNode(Config{RandomizedElectionTimeout: X}) and RawNode.Tick; the election fires at exactly tick X on every run (externally importable).
- Asynchronous Node path: StartNode/RestartNode with the same Config option; the node's raft state machine uses the fixed timeout for every reset (externally importable).
- rafttest env path: InteractionOpts.OnConfig sets Config.RandomizedElectionTimeout before each node is created; env.Tick produces deterministic election timing (externally importable).
- Module-internal test path: existing setRandomizedElectionTimeout / SetRandomizedElectionTimeout and the datadriven set-randomized-election-timeout command remain functional (same-package tests only).

### 未覆盖路径

- Internal network harness randomness (rafttest/network.go raftNetwork.rand): transport-simulation delay/loss randomness is outside the protocol system boundary; not implemented.

### 实际实现方式

- add_test_configuration: new library-level Config.RandomizedElectionTimeout option in raft.go, validated in Config.validate against the existing legal domain [ElectionTick, 2*ElectionTick-1]; zero keeps the randomized default.
- add_test_hook: resetRandomizedElectionTimeout consults the per-node fixed value (copied from Config in newRaft) before falling back to the unchanged globalRand draw; no protocol condition, message, or persistence semantics changed.
- reuse existing target test interfaces: module-internal setters setRandomizedElectionTimeout / SetRandomizedElectionTimeout (raft_test.go) and the rafttest datadriven set-randomized-election-timeout command (plumbed via interaction_test.go) are untouched and still work; rafttest InteractionOpts.OnConfig now also applies the validated option at node creation.

### 修改前已知限制（供对照）

- The existing test setter accepts arbitrary values without validation, defining an undocumented test-only domain; a new Config option should validate explicitly.
- The rafttest set-randomized-election-timeout command only works when this module's own tests plumb the function; other consumers cannot use it.

## 生命周期控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Node availability control inside the protocol library: Node.Stop, Node restart via StartNode/RestartNode (new instance reconstructed from Storage), RawNode discard/recreate, and the rafttest harness (internal pause/resume/stop/restart; public env has none). Real process supervision and WAL/disk durability are outside.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：Node.Stop and RestartNode/StartNode exist and are usable, but there is no single declared test facade tying stop and restore together for the public rafttest InteractionEnv; its nodes cannot be stopped/paused/restarted except by manually splicing env.Nodes[i].RawNode with a freshly built config.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- Asynchronous Node path: Stop() terminates the run loop; availability is restored by creating a NEW node via RestartNode/StartNode sharing the same Storage (reconstruction, not same-instance resume).
- Synchronous RawNode path: no lifecycle API; the test discards the RawNode and constructs NewRawNode with the same Storage.
- rafttest internal network harness (rafttest/node.go): pause buffers inbound messages and resumes them; stop/restart recreate the Node from the same MemoryStorage (in-package tests only).
- rafttest InteractionEnv (public): nodes have no stop/pause/restart command; only manual replacement of env.Nodes[i].RawNode through public fields.

### Analyzer 建议（修改前）

- Add stop/restart (or pause) commands to rafttest InteractionEnv, e.g. a 'stop-node idx' / 'restart-node idx' handler that swaps env.Nodes[idx].RawNode with raft.NewRawNode over the same Storage, or a paused flag consulted by ProcessReady/DeliverMsgs.
- Optionally export the internal pause/resume from rafttest/node.go as an env-level availability simulation, documented as availability-only with no crash-fidelity claim.

### 目标已有入口

- `Node.Stop()`
- `Node.StartNode(c, peers)`
- `Node.RestartNode(c)`
- `RawNode.NewRawNode(c)`
- `rafttest internal node.pause()/resume()/stop()/restart() (package-internal)`
- `rafttest Node struct fields RawNode/Storage/Config (public, manual reconstruction possible)`

### 本次生成接口

- 调用入口：`rafttest/interaction_env_handler_stop_node.go / InteractionEnv.StopNode：Makes the node at the given index unavailable by discarding all volatile in-memory state (RawNode, AppendWork, ApplyWork), recording the current applied index into Config.Applied, and setting Node.Stopped. Mirrors the internal harness stop semantics: all in-memory state of the node is discarded, all stable storage MUST be unchanged. After StopNode, every env operation that would drive the node's protocol state fails with an error.`

### 使用与范围

- 生产路径：unchanged: no protocol-library code modified; only the rafttest test-support package (public InteractionEnv facade and guards), datadriven handler registration, tests, and testdata were changed.
- 测试路径：rafttest.InteractionEnv public API (StopNode/RestartNode, Node.Stopped) plus datadriven commands stop-node/restart-node via InteractionEnv.Handle; no build tags or runtime flags required. Setup: nodes must be created with AddNodes (each node keeps its Config and Storage); StopNode/RestartNode operate on env node indices. Verified by TestInteractionEnvStopRestart (Go) and testdata/lifecycle.txt (datadriven).
- 缓存变化与失败语义：StopNode/RestartNode do not touch env.Messages. DeliverMsgs: for a non-drop recipient whose node is stopped, returns 0 and leaves all its messages in the cache ('not delivering to stopped node N' printed); after RestartNode the same messages can be delivered, after which they are removed from the cache. InjectMessage: a cached message targeting a stopped node returns an error and stays in the cache; on success against a running node the message is removed as before. Drop requests to stopped nodes still remove messages. ClearMessages and per-instance handles are unaffected.
- StopNode is an availability simulation only; it does not claim crash durability, fsync, or process supervision. Persistent/volatile semantics follow the existing rafttest harness: 'All in memory state of node is discarded. All stable MUST be unchanged.' Recoverable state (term, vote, commit, log, membership) is owned by the node's Storage and restored by NewRawNode.
- Error semantics: StopNode errors on already-stopped or out-of-range nodes; RestartNode errors on running or out-of-range nodes; all guarded node-driving entrypoints return the same descriptive error; ForgetLeader panics on a stopped node (no error return in its existing signature, kept unchanged).
- The applied index captured at stop time prevents the test state machine (Node.History) from re-applying committed entries after restart; the test verifies History length and indices are unchanged across the restart and that the restarted node catches up to the live commit index.
- Message-cache interaction: DeliverMsgs returns 0 for a stopped recipient and prints 'not delivering to stopped node N' while leaving the messages in env.Messages; InjectMessage returns an error and leaves the message cached; after RestartNode the same messages are deliverable. Drop requests to a stopped node remain allowed.
- Stabilize ignores stopped nodes; messages addressed to them accumulate in the cache without blocking termination, so a cluster can be stabilized while a node is down and again after restart.
- Only the public rafttest test-support package, datadriven handler registration, tests, and testdata were modified. No protocol-library file (raft.go, node.go, rawnode.go, storage.go, raftpb) was changed; production semantics are untouched.
- The prior message-capture/injection seam (DeliverMsgs, InjectMessage) was extended only to stay coherent with the new stopped state (refuse delivery into a stopped node); no message-capture or message-injection capability was added by this run.

### 已覆盖路径

- Synchronous InteractionEnv path (externally importable, new): StopNode discards the node's RawNode and pending storage work and marks Node.Stopped; RestartNode reconstructs a fresh RawNode from the preserved Config/Storage; every node-driving env entrypoint (ProcessReady, ProcessAppendThread, ProcessApplyThread, Tick, Campaign, Compact, Propose, ProposeConfChange, Status, SendSnapshot, TransferLeadership, ReportUnreachable, set-randomized-election-timeout handler, ForgetLeader handler) is guarded and fails on a stopped node; messages addressed to the stopped node remain in env.Messages and are delivered after restart.
- Datadriven path (externally importable, new): 'stop-node <idx>' and 'restart-node <idx>' commands registered in InteractionEnv.Handle; verified by testdata/lifecycle.txt which stops node 2, shows its stable raft-log stays readable, shows a driving command erroring, keeps the cluster progressing, restarts node 2, and confirms convergence.
- Asynchronous Node path (externally importable, pre-existing, unchanged): Node.Stop() terminates the run loop; availability is restored by constructing a NEW Node via RestartNode/StartNode over the same Storage (reconstruction, not same-instance resume).
- Synchronous RawNode path (externally importable, pre-existing, unchanged): the test discards the RawNode and constructs NewRawNode with the same Storage; the new env facade automates exactly this reconstruction for env nodes.
- rafttest internal network harness path (same-package tests only, pre-existing, unchanged): node.stop()/restart() recreate the Node over the same MemoryStorage; pause()/resume() buffer inbound messages (availability simulation only, no crash-fidelity claim).

### 未覆盖路径

- Public pause/resume (buffered unavailability) on InteractionEnv for external consumers: not implemented. The synchronous env has no background goroutine to suspend, and StopNode/RestartNode with messages left in flight in the authoritative cache covers the same availability-testing scenarios. The goroutine-based pause/resume remains in the internal network harness, which is unexported and usable by same-package tests only.

### 实际实现方式

- Extended the existing public rafttest test-support package (InteractionEnv) with a stop/restart lifecycle facade reusing the target-native reconstruction mechanism (raft.NewRawNode over the node's preserved Config/Storage); no core protocol code was touched.
- Added a public Node.Stopped flag as the single authoritative availability state; StopNode discards volatile state (RawNode, AppendWork, ApplyWork) and captures the applied index into Config.Applied so restart restores applied and does not re-apply already-committed entries.
- Guarded every env entrypoint that drives a node's protocol state with checkNodeRunning, returning 'node N is stopped; restart it with RestartNode before driving it again'; ForgetLeader has no error return, so it panics with a descriptive message on a stopped node.
- DeliverMsgs refuses non-drop delivery to a stopped recipient (messages stay in the authoritative env.Messages cache, count 0) and InjectMessage errors while leaving the message cached, keeping the message-control seam consistent with the stopped state; Stabilize skips stopped nodes and drives the remaining nodes to a fixed point.
- RaftLog remains readable on a stopped node (Storage survives, matching 'stable MUST be unchanged'); raft-state prints stopped nodes as 'N: stopped'.
- Added datadriven commands stop-node/restart-node, a Go unit test (rafttest/interaction_env_lifecycle_test.go), and a datadriven testdata file (testdata/lifecycle.txt).

### 修改前已知限制（供对照）

- Pause/resume in the internal harness is availability simulation only and must not be described as production crash recovery.
- Crash-fidelity and durability are owned by the application's Storage implementation; real WAL/disk is outside the boundary.

## 状态观察

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Read-only state observation inside the library: RawNode.Status/BasicStatus/WithProgress, Node.Status, and rafttest RaftLog/RaftState/Status handlers plus the Storage interface for log ranges. Application state machines and external monitoring are outside.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The public Status/BasicStatus/WithProgress APIs and the Storage interface directly satisfy the v0.1 observation contract (role, term, commit index, applied index, log range) with snapshot-safe copies; rafttest handlers reuse them read-only.

### Analyzer 发现的实现路径（修改前）

- Synchronous RawNode path: Status()/BasicStatus()/WithProgress() read raft state directly with copies.
- Asynchronous Node path: Node.Status() round-trips through the status channel to getStatus.
- rafttest env path: RaftLog reads the node Storage log range; raft-state prints role/term/lead for every node.

### 目标已有入口

- `RawNode.Status()`
- `RawNode.BasicStatus()`
- `RawNode.WithProgress(visitor)`
- `Node.Status()`
- `Storage.Entries/FirstIndex/LastIndex/Term/Snapshot (log range)`
- `rafttest InteractionEnv.RaftLog(idx), handleRaftState(), Status(idx)`

### 当前限制

- Progress is populated only on the leader (documented Status semantics).
- Status is a point-in-time copy; it does not expose internal raftLog structures beyond the documented fields.
- Log-range observation requires the application-side Storage; the raft library does not own a log store of its own.

## 外部输入

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Application workload entrypoints of the raft protocol library: proposal, configuration-change proposal, and linearizable read requests. Peer-to-peer protocol ingress (Step with MsgApp/MsgVote/MsgHeartbeat/MsgSnap), tick-generated local messages (MsgHup/MsgBeat/MsgCheckQuorum), and internal storage-thread messages (MsgStorageAppend/MsgStorageApply and their responses) are excluded.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The workload entrypoints are public, documented and directly callable by external tests (e.g. example_test.go's Ready loop, rafttest Propose handler); no additional target code is needed for this discovery capability.

### Analyzer 发现的实现路径（修改前）

- Asynchronous Node path: Node.Propose/ProposeConfChange/ReadIndex enqueue a MsgProp/MsgReadIndex (propc or recvc) and the node.run loop steps it into r.Step.
- Synchronous RawNode path: RawNode.Propose/ProposeConfChange/ReadIndex call rn.raft.Step directly with MsgProp/MsgReadIndex.
- rafttest env path: env.Propose/ProposeConfChange call the embedded RawNode entrypoints of env.Nodes[idx].

### 目标已有入口

- `Node.Propose(ctx, data)`
- `Node.ProposeConfChange(ctx, cc)`
- `Node.ReadIndex(ctx, rctx)`
- `RawNode.Propose(data)`
- `RawNode.ProposeConfChange(cc)`
- `RawNode.ReadIndex(rctx)`
- `rafttest InteractionEnv.Propose(idx, data)`
- `rafttest InteractionEnv.ProposeConfChange(idx, cc)`

### 当前限制

- Proposals can be dropped without notice (documented ErrProposalDropped behavior); this is protocol semantics, not an entrypoint gap.
- Real network and application state machines are outside the system boundary.

## 独立 Reviewer 结论

- 总体结论：`REVISE_AGENT2`

### 阻塞问题

- [message_capture] cloneMessage misses Snapshot.Metadata.ConfState nested slices (Voters, Learners, VotersOutgoing, LearnersNext). A test mutating em.Msg.Snapshot.Metadata.ConfState.Voters[0] on an enumerated/taken snapshot would mutate the cached message's snapshot and can alias raft's unstable or storage snapshot. This violates snapshot_safety and contradicts the interface report's 'deep clone of every mutable field' claim. The added TestInteractionEnvMessageSnapshotSafety only mutates Context, Entries[].Data, and Snapshot.Data, so it does not exercise this path.（rafttest/interaction_env_handle.go / cloneMessage）
- [message_capture] The interface report's message_capture usage example uses raftConfigStub(), an unexported helper, while declaring the facade as externally importable (go.etcd.io/raft/v3/rafttest). An external consumer cannot compile that example, so the usage example does not match the declared consumer scope and setup.（rafttest/interaction_env.go / raftConfigStub）

### 非阻塞剩余风险

- env.Messages remains an exported field while msgIDs is private; the facade keeps them aligned only through its own helpers. All in-tree mutation paths (ProcessReady, SendSnapshot, ProcessAppendThread, ProcessApplyThread, DeliverMsgs) are rewired, and direct external splicing of env.Messages is documented as unsupported, but such direct mutation can still desynchronize handles and make EnumerateMessages mis-index or panic.
