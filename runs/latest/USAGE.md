# etcd-raft 测试接口使用报告

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
能力状态、源码证据和完整限制以 `capability-report.json` 为准。

## 消息捕获

- 分析状态：`PATCHABLE`
- 覆盖边界：Ready processing and rafttest support are inside the boundary; real network send and WAL are outside.
- 现有测试接口是否完整：否
- 测试支持判断：env.Messages is a raw exported slice: no stable message IDs, no callable ListPending/ClearPending, and the Node-async path has no capture at all. Per the capture contract this is only a primitive, so additional rafttest support is required.
- 本次修改：已生成接口

### Analyzer 发现的实现路径

- RawNode synchronous path: readyWithoutAccept exposes r.msgs (rawnode.go:147); ProcessReady moves rd.Messages into env.Messages; no automatic continuation (delivery only via DeliverMsgs/Stabilize)
- Node async goroutine path: node.run emits Ready on readyc (node.go:440); rafttest/node.go goroutine sends rd.Messages via iface.send immediately (rafttest/node.go:85-91) - no pending store
- AsyncStorageWrites path: MsgStorageAppend/MsgStorageApply go to AppendWork/ApplyWork (process_ready.go:60-76); their Responses are appended to env.Messages after thread processing (process_append_thread.go:77, process_apply_thread.go:67)

### 建议改造

- Extend rafttest.InteractionEnv with a captured-message store that assigns a stable control-plane ID when ProcessReady parks messages, plus ListPending() and ClearPending() entrypoints.
- Add a capture hook in rafttest/node.go's Ready loop (line 85) to route rd.Messages into the same pending store instead of iface.send.
- Keep suppression semantics: messages stay parked until explicitly delivered (DeliverMsgs/Stabilize already guarantee no auto-continuation on the RawNode path).
- Declare ID scope (per-InteractionEnv pending store) in the interface report.

### 目标已有入口

- `RawNode.Ready / readyWithoutAccept (rawnode.go:133, 141)`
- `rafttest ProcessReady (rafttest/interaction_env_handler_process_ready.go:45)`
- `rafttest env.Messages pending slice (rafttest/interaction_env.go:52)`
- `rafttest ProcessAppendThread / ProcessApplyThread (rafttest/interaction_env_handler_process_append_thread.go:47, process_apply_thread.go:46)`
- `rafttest node Ready loop (rafttest/node.go:74)`

### 本次生成接口

- 捕获位置：`rafttest/interaction_env_handler_process_ready.go / (*InteractionEnv).capturePending：Capture point where protocol output is intercepted: Ready.Messages in ProcessReady, storage-thread responses in ProcessAppendThread/ProcessApplyThread, and SendSnapshot MsgSnap are parked with stable control-plane IDs instead of continuing along their original path`
- Pending Store：`rafttest/interaction_env.go / InteractionEnv.pending：Per-InteractionEnv pending store: pending []PendingMessage records with capture-time IDs (nextPendingID); the rafttest async node harness keeps a separate per-node store (node.captured/capturedID) guarded by mu`
- 调用入口：`rafttest/pending_msgs.go / (*InteractionEnv).ListPending：Callable list-pending entrypoint over the capture store; ClearPending (same file) is the companion clear entrypoint; both operate on the InteractionEnv pending store`

### 使用与范围

- 生产路径：Unchanged: no production raft package code modified; capture support lives entirely in the rafttest test-support package
- 测试路径：InteractionEnv capture is always active in rafttest: ProcessReady/ProcessAppendThread/ProcessApplyThread/SendSnapshot park protocol output, and nothing auto-continues; the rafttest async node harness requires opt-in startNodeWithCapture, while default startNode preserves the pre-existing auto-send behavior
- 消息 ID 范围：pending_store_instance
- 复制策略：Captured raftpb.Message values are appended to the store at capture time with an incrementing control-plane ID; ListPending returns a defensive copy of the store slice; delivery/drop removes handled records from env.pending (splitPending) in lockstep with env.Messages (splitMsgs); ClearPending resets both
- Message IDs are test-control identity assigned at capture time (env.nextPendingID for InteractionEnv, node.capturedID for the async harness); they are never derived from protocol term/index/type/payload and are not added to any protocol message schema
- Captured messages never continue automatically: on the RawNode path they are parked in env.Messages and env.pending and delivered only via DeliverMsgs/Stabilize; on the async harness path capture mode replaces iface.send with the pending store
- DeliverMsgs and drop handling consume handled messages from both env.Messages and env.pending, so delivered/dropped messages no longer appear in ListPending
- AsyncStorageWrites responses are protocol output produced when the storage threads are processed; they are captured in ProcessAppendThread and ProcessApplyThread; SendSnapshot parks its MsgSnap in the same store
- ID scope is per pending-store instance: unique within each InteractionEnv, and within each capture-mode async harness node; cross-node uniqueness is not required by the contract
- The default rafttest node harness (startNode) keeps its existing auto-send behavior; existing node_test.go and node_bench_test.go are unchanged
- Real network send and WAL/disk are outside the system boundary; capture covers protocol output inside the module only
- No scheduling policy is implemented; pending records are listed in capture order and delivery follows existing splitMsgs semantics
- Verification: go test -run '^$' ./... and go test ./rafttest/... pass (checked with readonly go_test/go_test_compile); no production raft package code was modified

### 已覆盖路径

- RawNode synchronous path: InteractionEnv.ProcessReady parks rd.Messages via capturePending into env.pending (stable capture-time IDs) and env.Messages; captured messages do not continue automatically and are delivered only when explicitly handed to a node Step entrypoint via DeliverMsgs/Stabilize
- AsyncStorageWrites path: storage-thread responses produced by ProcessAppendThread and ProcessApplyThread are parked via capturePending; SendSnapshot-generated MsgSnap is parked via capturePending
- Node async goroutine path (rafttest harness): opt-in startNodeWithCapture parks Ready-loop rd.Messages in a per-node pending store instead of sending over iface; listPending/clearPending accessors expose the store

### 实际实现方式

- add_pending_store: per-InteractionEnv pending store (InteractionEnv.pending/nextPendingID) and per-node store in the rafttest async harness (node.captured/capturedID) assigning stable control-plane IDs at capture time
- add_test_hook: capturePending called at ProcessReady, ProcessAppendThread, ProcessApplyThread, and SendSnapshot; DeliverMsgs keeps the store in sync by removing delivered/dropped records
- add_test_only_wrapper: opt-in startNodeWithCapture/listPending/clearPending on the rafttest async node harness covering the Node-async goroutine path; default startNode behavior is unchanged
- add_target_language_tests: rafttest/pending_msgs_test.go covering capture, no-auto-continuation, delivery consumption, ClearPending, capture order, defensive copy, and the async harness path

### 限制

- Real network send (outside boundary) is not captured; only the protocol output inside the module.
- Path coverage: RawNode and AsyncStorageWrites paths park messages; the Node-async goroutine path (rafttest/node.go) does not.

## 消息注入

- 分析状态：`PATCHABLE`
- 覆盖边界：Injection enters Node.Step / RawNode.Step (normal protocol input); no direct mutation of protocol state; real transport outside.
- 现有测试接口是否完整：否
- 测试支持判断：Delivery through the normal input boundary with preserved sender/receiver/content exists, but the contract requires selecting one captured message by a stable control-plane ID; IDs do not exist yet and there is no inject-by-ID entrypoint or declared ID scope.
- 本次修改：已生成接口

### Analyzer 发现的实现路径

- RawNode synchronous path: DeliverMsgs -> env.Nodes[toIdx].Step(msg) (deliver_msgs.go:97-101); synchronous delivery; sender/receiver/content preserved
- Node async goroutine path: node.Step(ctx,m) -> recvc (node.go:516) -> run loop -> raft.Step (node.go:404); asynchronous delivery
- AsyncStorageWrites path: storage-thread Responses appended to env.Messages (process_append_thread.go:77) and later delivered to the node via Step; MsgStorageAppend/MsgStorageApply can also be stepped directly

### 建议改造

- Add InteractionEnv.InjectByID(id) that selects a captured message from the pending store by stable control-plane ID and delivers it through the recorded target binding (env.Nodes[toIdx].Step, or node.Step on the async path).
- Assign IDs at capture time in the same store built for message_capture; document ID scope (per-InteractionEnv pending store).
- Verify sender/receiver/content preservation in tests after injection; keep injection confined to Step so protocol state is not mutated directly.

### 目标已有入口

- `RawNode.Step (rawnode.go:118)`
- `Node.Step / stepWithWaitOption (node.go:478, 513)`
- `rafttest DeliverMsgs (rafttest/interaction_env_handler_deliver_msgs.go:81)`
- `rafttest env.Nodes target binding (rafttest/interaction_env.go:51)`
- `rafttest node iface / pause-resume buffering (rafttest/node.go:93, 101-114)`

### 本次生成接口

- 捕获位置：`rafttest/interaction_env_handler_process_ready.go / (*InteractionEnv).ProcessReady：Capture boundary that parks protocol output in the pending store with stable control-plane IDs; the same store (also fed by ProcessAppendThread/ProcessApplyThread/SendSnapshot and, on the Node-async path, by the node Ready loop in capture mode) is the injection source.`
- Pending Store：`rafttest/pending_msgs.go / PendingMessage：Captured-message store: PendingMessage{ID, Msg}; IDs are assigned at capture time by capturePending, are unique within the store, and are not derived from protocol fields; records are mirrored into InteractionEnv.Messages so the existing delivery machinery stays consistent.`
- 调用入口：`rafttest/inject.go / (*InteractionEnv).InjectByID：Callable inject-by-stable-ID entrypoint: selects one captured message from the env pending store and delivers it unchanged through the recipient's normal protocol input entrypoint (env.Nodes[Msg.To-1].Step on the RawNode and AsyncStorageWrites paths).`

### 使用与范围

- 生产路径：Unchanged: no raft core (production) code was modified; injection is confined to the rafttest test-support package. Protocol conditions, message semantics, persistence semantics, and crash/restart behavior are untouched.
- 测试路径：Enabled by the rafttest test environment: the InteractionEnv pending store (fed by ProcessReady, ProcessAppendThread/ProcessApplyThread, SendSnapshot) and the node harness capture mode (startNodeWithCapture). ListPending exposes stable IDs for selection; InjectByID consumes and delivers.
- 消息 ID 范围：pending_store_instance
- 复制策略：The captured raftpb.Message is passed by value and unchanged to RawNode.Step / iface.send; ListPending returns a defensive copy of the PendingMessage records; the delivered message is returned to the caller unchanged so sender, receiver, and content can be verified.
- Error semantics preserved: on the RawNode path, synchronous errors returned by RawNode.Step (ErrStepLocalMsg for local messages from non-local senders, ErrStepPeerNotFound for response messages from unknown peers, and errors propagated from raft.Step) are returned unchanged, and the message is left pending so the caller can retry it, drop it (DeliverMsgs with Drop), or discard it (ClearPending).
- If the requested ID is not pending, or the recipient node (Msg.To) is not part of the env, InjectByID returns an error and consumes nothing.
- env.pending and env.Messages stay aligned (capturePending appends the same messages to both; DeliverMsgs/ClearPending remove from both), so InjectByID removes the consumed message from both at the same index; the remaining queue stays deliverable by DeliverMsgs/Stabilize.
- Node async path: delivery is routed via the node's iface (the existing simulated transport). Like any iface.send it is asynchronous and may drop the message when the recipient is disconnected, matches a dropmap entry, or has a full receive queue (existing harness semantics); the selected record is consumed when routed.
- ID scope: per-InteractionEnv pending store (pending_store_instance) for InteractionEnv.InjectByID; the node harness maintains a separate per-node store (startNodeWithCapture), so its IDs are unique per node.
- The async-path test pauses the recipient node until the vote is injected so the test is deterministic; the recipient then steps the buffered message through Node.Step on resume, using existing pause/resume harness semantics.
- No scheduling policy, wait-for-quiescence operation, or new protocol error model was introduced; the datadriven handler set was not extended (InjectByID is a callable Go entrypoint).
- No existing files were modified: injection was added in new files rafttest/inject.go and rafttest/inject_test.go, reusing the already-present pending store.

### 已覆盖路径

- RawNode synchronous path: messages parked by ProcessReady are injected by stable ID via env.Nodes[Msg.To-1].Step; delivery is synchronous, only the selected message is consumed after success, and sender/receiver/content are preserved.
- AsyncStorageWrites path: storage-thread responses parked by ProcessAppendThread/ProcessApplyThread are injected by stable ID through the same env entrypoint into the node's RawNode.Step (same target binding as DeliverMsgs).
- Node async goroutine path: messages parked by the node Ready-loop capture mode (startNodeWithCapture) are injected by stable ID via (*node).injectByID, routed through the existing iface into the recipient's receive queue, which the recipient's run loop feeds into Node.Step.

### 实际实现方式

- Reused the existing rafttest pending store (PendingMessage/capturePending) as the injection source: stable control-plane IDs are assigned at capture time and are not protocol-message fields.
- Added exported test-only entrypoint InteractionEnv.InjectByID(id) that selects by stable ID and delivers through the recipient's real RawNode binding (env.Nodes[Msg.To-1].Step), consuming only the selected message after success.
- Added test-only entrypoint (*node).injectByID(id) on the rafttest node harness (unexported, consistent with listPending/clearPending) that routes the selected captured message through the existing iface into the recipient's Node.Step.
- Added Go tests (rafttest/inject_test.go) covering the RawNode path, unknown-ID handling, consume-only-selected semantics, the AsyncStorageWrites path, and the Node async path.

### 限制

- Injection on the Node-async path requires a started node wrapper (rafttest/node.go) with its own goroutine; delivery is asynchronous.
- Real transports outside the boundary are not injection targets; only protocol input entrypoints are used.

## 时间控制

- 分析状态：`SUPPORTED`
- 覆盖边界：Tick-driven clock inside the raft core; wall-clock tickers used by test harnesses outside the protocol core.
- 现有测试接口是否完整：是
- 测试支持判断：Explicit Tick satisfies the explicit_tick accepted form directly on both Node and RawNode; the protocol's only time inputs are tick counters, so no coordination wrapper or injectable clock is required.

### Analyzer 发现的实现路径

- Node async path: Node.Tick -> tickc (buffered, node.go:328) -> run loop (node.go:438-439) -> rn.Tick -> raft.tick()
- RawNode synchronous path: RawNode.Tick -> raft.tick() (rawnode.go:64-66)
- rafttest path: env.Tick(idx, n) loops explicit Tick calls (rafttest/interaction_env_handler_tick.go:34-38)

### 目标已有入口

- `Node.Tick (node.go:463)`
- `RawNode.Tick (rawnode.go:64)`
- `RawNode.TickQuiesced (rawnode.go:78)`
- `raft.tickElection / tickHeartbeat (raft.go:850, 862)`
- `rafttest tick-election / tick-heartbeat handlers (rafttest/interaction_env_handler_tick.go:23-31)`

### 限制

- rafttest/node.go uses a real 5ms time.Ticker (rafttest/node.go:67) in its demo Node wrapper; that is harness-side and not part of the protocol's time model.
- No injectable wall-clock exists, but none is needed: the protocol has no wall-clock reads.

## 随机性控制

- 分析状态：`PATCHABLE`
- 覆盖边界：Randomized election timeout selection inside the raft core; test harnesses outside.
- 现有测试接口是否完整：否
- 测试支持判断：The shipped library exposes no Config option, injected source, or hook for the randomized election timeout; the sole setter is a test-only symbol and is clobbered on state transitions, so external test code cannot produce repeatable random choices.
- 本次修改：已生成接口

### Analyzer 发现的实现路径

- Election path: becomeFollower/becomeCandidate -> r.reset (raft.go:784) -> resetRandomizedElectionTimeout -> globalRand.Intn(crypto/rand) -> randomizedElectionTimeout [electionTimeout, 2*electionTimeout)
- rafttest path: set-randomized-election-timeout handler -> Options.SetRandomizedElectionTimeout -> raft.SetRandomizedElectionTimeout direct field write (test-only, resets on next state transition)

### 建议改造

- Add a Config option (e.g., RandomizedElectionTimeout override or a small rand-source hook) consulted in resetRandomizedElectionTimeout (raft.go:2049).
- Alternatively promote a public RawNode setter that suppresses re-randomization when set (guard in r.reset).
- Wire the option through rafttest raftConfigStub/AddNodes so data-driven tests no longer depend on the test-file export.

### 目标已有入口

- `raft.resetRandomizedElectionTimeout (raft.go:2049)`
- `raft.reset -> resetRandomizedElectionTimeout (raft.go:793)`
- `raft.SetRandomizedElectionTimeout (raft_test.go:4098, test-only export)`
- `rafttest InteractionOpts.SetRandomizedElectionTimeout (rafttest/interaction_env.go:31-33)`
- `rafttest set-randomized-election-timeout handler (rafttest/interaction_env_handler_set_randomized_election_timeout.go:24)`

### 本次生成接口

- 调用入口：`raft.go / Config.RandomizedElectionTimeout：New shipped Config option: when non-zero, pins the randomized election timeout; applied at node creation (newRaft) and re-applied on every reset (role transition) inside resetRandomizedElectionTimeout. Zero (default) preserves the existing randomized draw.`

### 使用与范围

- 生产路径：Unchanged default: with Config.RandomizedElectionTimeout == 0, resetRandomizedElectionTimeout (raft.go) executes the identical electionTimeout + globalRand.Intn(electionTimeout) draw as before; the override path is only entered when the option is explicitly set.
- 测试路径：Set Config.RandomizedElectionTimeout on every node (e.g., to ElectionTick); the value is pinned at creation and re-applied on each role transition, so identical configs yield repeatable election timing. rafttest users set it per node via InteractionOpts.OnConfig; existing in-repo data-driven tests are unaffected.
- No protocol conditions, term/quorum/commit logic, message semantics, persistence semantics, or the election-timeout algorithm were changed; the default code path is identical.
- The option is deliberately lenient: any non-zero value is honored; values outside [ElectionTick, 2*ElectionTick) deviate from the randomized default's range but remain valid for tests.
- The pinned value is applied at construction and re-applied on every reset, fixing the reported gap that the test-only setter was overwritten on the next role transition.
- Same-initial-state repeatability: nodes created from identical Configs with the option set produce identical election timing (verified by TestConfigRandomizedElectionTimeoutDeterminism); no seed is needed because the random draw is bypassed, not seeded.
- The existing in-repo test-only raft.SetRandomizedElectionTimeout (raft_test.go) and the rafttest data-driven command are untouched and keep working for in-repo tests.
- The Node async path (StartNode) and the RawNode synchronous path share newRaft, so both construction paths are covered by the same Config option.
- Verification: go test ./... passes for go.etcd.io/raft/v3, rafttest, and all subpackages.

### 已覆盖路径

- RawNode/Node construction path: NewRawNode/StartNode/RestartNode -> newRaft -> Config.RandomizedElectionTimeout pins randomizedElectionTimeout at creation (initial becomeFollower reset honors the override).
- Election path: becomeFollower/becomeCandidate/becomeLeader -> reset (raft.go) -> resetRandomizedElectionTimeout now re-applies the pinned value on every role transition instead of re-randomizing; with the option unset the original globalRand.Intn draw is unchanged.
- rafttest node construction path: InteractionOpts.OnConfig (invoked per node by AddNodes before NewRawNode) can set Config.RandomizedElectionTimeout, giving data-driven harnesses deterministic election timing without relying on the repo-internal test export.

### 未覆盖路径

- rafttest data-driven set-randomized-election-timeout command for consumers outside this module: the command still routes through the repo-internal test-only export raft.SetRandomizedElectionTimeout (raft_test.go), which is not part of the shipped library. Reason: the handler intentionally keeps one-shot semantics ('will be reset again when the node changes state'); repointing it to a pinned override would change existing data-driven behavior and add new shipped surface. Workaround: set the option via InteractionOpts.OnConfig at AddNodes time.

### 实际实现方式

- add_test_configuration: new shipped Config.RandomizedElectionTimeout option consulted by resetRandomizedElectionTimeout; 0 keeps the existing randomized behavior exactly.
- add_test_hook: unexported fixedElectionTimeout flag on raft with an early return in resetRandomizedElectionTimeout so the pinned value survives every reset/role transition (fixing the gap where the prior test-only setter was clobbered by r.reset).
- add_target_language_tests: new randomized_election_timeout_test.go covering the default range, the override across follower/candidate/pre-candidate/leader transitions, and two-node determinism at exactly the configured tick.

### 限制

- Same seed determinism is impossible with crypto/rand; even a fixed value is lost on each becomeFollower/becomeCandidate/becomeLeader.
- rafttest data-driven tests work only because raft_test.go exports the setter within this repo's test builds.

## 生命周期控制

- 分析状态：`SUPPORTED`
- 覆盖边界：Node lifecycle and Storage-owned persistent state inside the module; process supervision, WAL/disk, and external recovery tooling outside.
- 现有测试接口是否完整：是
- 测试支持判断：Public APIs (StartNode, RestartNode, NewRawNode, Bootstrap, Node.Stop, Config.Applied, MemoryStorage) already compose into creation/stop/recovery tests without new target code; no persistent/volatile split needs to be invented.

### Analyzer 发现的实现路径

- Node async path: StartNode/RestartNode spawn node.run goroutine; Stop signals the run loop (node.go:454-456) and blocks on done
- RawNode synchronous path: NewRawNode/Bootstrap create a thread-unsafe node with no goroutine; lifecycle is the application's (no Stop on RawNode)
- Recovery path: RestartNode -> NewRawNode -> newRaft reads Storage.InitialState (raft.go:442)

### 目标已有入口

- `Node.Stop (node.go:336)`
- `StartNode (node.go:276)`
- `RestartNode (node.go:286)`
- `RawNode.Bootstrap (bootstrap.go:30)`
- `NewRawNode (rawnode.go:51)`
- `Config.Applied / Config.Storage (raft.go:144-149)`
- `rafttest node stop/restart/pause/resume (rafttest/node.go:122, 131, 151, 156)`

### 限制

- Crash recovery beyond Storage contents (disk/WAL) is outside the boundary.
- RawNode has no Stop; lifecycle control for the synchronous path is only creation and abandonment, which is inherent to its thread-unsafe design.

## 状态观察

- 分析状态：`SUPPORTED`
- 覆盖边界：Node/RawNode status APIs and module-provided Storage inside the boundary; application state machine internals outside.
- 现有测试接口是否完整：是
- 测试支持判断：The Status API plus MemoryStorage accessors directly satisfy the observation contract (role, term, commit_index, applied_index, log_range) without new target code; a read-only wrapper is unnecessary.

### Analyzer 发现的实现路径

- RawNode synchronous path: Status/BasicStatus/WithProgress direct read of raft state (status.go:68)
- Node async path: Node.Status round-trips through the status channel in node.run (node.go:452-453)
- rafttest paths: status/raft-state handlers call n.Status(); raft-log handler reads Storage

### 目标已有入口

- `Node.Status (node.go:574)`
- `RawNode.Status (rawnode.go:498)`
- `RawNode.BasicStatus (rawnode.go:505)`
- `RawNode.WithProgress (rawnode.go:521)`
- `MemoryStorage.FirstIndex/LastIndex/Term/Entries (storage.go:186, 174, 159, 135)`
- `rafttest status/raft-log/raft-state handlers (rafttest/interaction_env_handler_status.go:33, raft_log.go:33, raftstate.go:36)`

### 限制

- RawNode/Node do not expose an in-memory firstIndex; log range is read through Storage, which is application-backed outside the boundary for real deployments.
- Status.Progress is only populated on the leader (status.go:71-73).

## 外部输入

- 分析状态：`SUPPORTED`
- 覆盖边界：Public Node/RawNode protocol APIs inside the module; real application state machines and transport outside. v0.1 adds no new business-input API.
- 现有测试接口是否完整：是
- 测试支持判断：Node/RawNode public APIs directly expose proposals, membership changes, and read requests; rafttest propose/propose-conf-change/campaign handlers wrap them without new target code.

### Analyzer 发现的实现路径

- RawNode synchronous path: RawNode.Propose/ProposeConfChange/ReadIndex/Campaign -> raft.Step
- Node async goroutine path: Node.Propose/ProposeConfChange/ReadIndex/Campaign -> propc/recvc channels -> node.run -> raft.Step
- rafttest InteractionEnv handlers -> same RawNode methods

### 目标已有入口

- `Node.Propose (node.go:474)`
- `Node.ProposeConfChange (node.go:495)`
- `Node.ReadIndex (node.go:613)`
- `Node.Campaign (node.go:472)`
- `Node.TransferLeadership / Node.ForgetLeader (node.go:600, 609)`
- `RawNode.Propose (rawnode.go:90)`
- `RawNode.ProposeConfChange (rawnode.go:101)`
- `RawNode.ReadIndex (rawnode.go:561)`
- `RawNode.Campaign (rawnode.go:83)`
- `rafttest InteractionEnv.Propose / Campaign (rafttest/interaction_env_handler_propose.go:32, campaign.go:29)`

### 限制

- Application state machines and real transports consuming Propose/Ready are outside the boundary.
- Proposals may be dropped (ErrProposalDropped) by design; retry semantics are the application's concern.
