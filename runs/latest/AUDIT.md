# etcd-raft 测试接口审计报告

> [!WARNING]
> 本次运行未完成，以下内容仅反映中断前已经产生的阶段性结果。
> 生成接口、调用示例和 Reviewer 结论可能缺失，不得作为最终使用说明。

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
Analyzer 内容描述修改前状态；生成接口和 Reviewer 内容描述候选修改后状态。
机器可读细节以`capability-report.json`、`interface-report.json`为准。

## 消息捕获

- 修改前分析状态：`PATCHABLE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：The capture mechanics (output retained before delivery, single consumer, no racing) are already correct on all paths, but the cache operations are not: the direct paths expose a raw output collection (caller-created slice, explicitly a primitive per the contract), and rafttest exposes only bulk recipient/type selection plus an exported slice that the consumer would have to hand-edit for exact-instance Take/Drop/Clear.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- RawNode direct drive: output = rn.Ready().Messages (ownership transferred, r.msgs cleared); no automatic delivery; continuation via rn.Advance(rd). Cache = caller-held slice (primitive; enumerate by index, Take/Drop/Clear hand-written). Input boundary = rn.Step; target = test-owned RawNode instances; routing via m.To/m.From.
- Node channel drive: output = Ready delivered on readyc; messages handed to the caller; continuation via n.Advance(). Cache = caller-held slice (primitive). Input boundary = n.Step(ctx,m); targets mapped by m.To.
- rafttest InteractionEnv: output = ProcessReady(idx) moves non-local messages into env.Messages (env-owned cache; with AsyncStorageWrites, MsgStorageAppend/Apply go to AppendWork/ApplyWork and their responses re-enter env.Messages via ProcessAppendThread/ProcessApplyThread). Delivery only via DeliverMsgs/Stabilize; enumerate via exported field; no exact-instance Take/Drop; no Clear.

### Analyzer 建议（修改前）

- Add exported exact-instance cache operations to rafttest over env.Messages, e.g. TakeMsg(pred func(raftpb.Message) bool) (raftpb.Message, bool) removing and returning one selected message with its routing fields, DropMsgs(pred), and ClearMessages(), keeping DeliverMsgs as the combined delivery call.
- Add a thin exported capture wrapper for the direct paths (e.g. in rafttest: a Driver type wrapping *raft.RawNode that owns a message cache populated from Ready().Messages with Take/Drop/Clear and Advance), so the RawNode and Node direct routes gain a complete capture interface without changing protocol semantics.
- Optionally export an exact-instance helper that preserves message order and reports the target node index/id for each taken message so the test can map to its own runtime objects.

### 目标已有入口

- `raft.RawNode.Ready`
- `raft.RawNode.Advance`
- `raft.Node.Ready`
- `raft.Node.Advance`
- `rafttest.InteractionEnv.ProcessReady`
- `rafttest.InteractionEnv.Messages`
- `rafttest.InteractionEnv.DeliverMsgs`
- `rafttest.InteractionEnv.ProcessAppendThread`
- `rafttest.InteractionEnv.ProcessApplyThread`

### 本次生成接口

- 捕获位置：`rafttest/driver.go / Driver.Ready：Retains Ready.Messages in the owned cache and suppresses automatic delivery; the same retention semantics exist on the rafttest env path at InteractionEnv.ProcessReady (existing) and on the Node channel path at the test's receive from n.Ready() plus MessageCache.Add`
- Pending Store：`rafttest/message_cache.go / MessageCache：Ordered cache of retained outbound messages; the rafttest env path applies the same exact-instance operations directly to the existing env.Messages in-flight cache`
- 调用入口：`rafttest/driver.go / Driver.Ready：Capture seam for the direct RawNode path: retains Ready.Messages in the driver-owned cache before delivery and suppresses automatic continuation`

### 使用与范围

- 生产路径：Unchanged. All changes are additive exported APIs in the rafttest package; no protocol conditions, messages, persistence, recovery, or business input modified; the production default (no cache, no wrapper) is untouched.
- 测试路径：New exported rafttest APIs (MessageCache, Driver, InteractionEnv cache operations) exercised by new focused tests in rafttest/message_cache_test.go (TestMessageCache, TestDriverCaptureAndDeliver, TestInteractionEnvCacheOps). No existing test files were modified.
- 缓存实例引用：A cached instance is the target-native raftpb.Message value retained in cache order; TakeMsg/DropMsg/DeliverMsg select by predicate and return or remove the exact retained instance with its routing fields (From, To, Type). Once removed, a later Take cannot return it; selection always runs over the current cache contents, so a stale reference is rejected by absence and never silently retargets another message. No permanent numeric message IDs are introduced; identity is the retained instance itself, stable for as long as it stays in the cache.
- 目标绑定方式：Capture returns routing information with each taken instance. Binding to a real target happens at injection: on the rafttest env path the destination is resolved from the message's To against env.Nodes (the env-owned registry); on the RawNode path the test owns the node mapping and either passes it to Driver.Deliver as a bind function (which maps and validates To) or calls the target's Step directly after TakeMsg. Identifier arithmetic is not used as binding; the env registry or the test's own map validates the relationship.
- 缓存变化与失败语义：Enumerate (Messages/Len): returns an ordered deep-copied snapshot; the cache is unchanged. TakeMsg: removes and returns the selected instance; the cache shrinks by one. DropMsg/DropMsgs: remove the selected instance(s) without delivering. Clear/ClearMessages: remove all instances. Delivery (DeliverMsg/Driver.Deliver): the entry is removed before Step runs; a synchronous Step error is returned without restoring the entry; no match (ErrNoMessage) or unknown target leaves the cache unchanged. Unconfirmed asynchronous delivery does not exist in this library: Step is synchronous and its effects surface in the target's next Ready, which re-enters the same cache (env.Messages via ProcessReady, or the driver/MessageCache via Ready capture).
- 可选消息 ID 范围：pending_store_instance
- 复制策略：Enumeration snapshots (MessageCache.Messages, Driver.Messages) deep-copy each message: Entries (including each Entry.Data), Context, Snapshot value plus Data and ConfState slices (Voters, Learners, VotersOutgoing, LearnersNext), and Responses recursively, so returned snapshots do not alias cached, protocol, or controller state. Take/Drop/Clear operate on the exact retained instance (ownership transfer), matching the module's value semantics for pb.Message.
- All new entrypoints are externally exported from the go.etcd.io/raft/v3/rafttest package and work in an ordinary non-_test.go import without same-package access.
- The existing rafttest DeliverMsgs bulk recipient/type selection and the exported env.Messages field remain for the datadriven harness; the new exact-instance operations are additive and replace hand-written slice surgery for programmatic tests.
- With AsyncStorageWrites, ProcessReady continues to route the local storage-thread messages (MsgStorageAppend/MsgStorageApply) into the pre-existing AppendWork/ApplyWork queues and their responses re-enter env.Messages via ProcessAppendThread/ProcessApplyThread; the new exact-instance ops cover the in-flight cache env.Messages, including those responses.
- The direct RawNode path already transferred Ready.Messages ownership to the caller and the Node path already had a single channel consumer; the new cache layers add retention, enumeration, and exact-instance control at those capture points without changing protocol behavior.
- The full module test suite (go test ./...) passes; existing tests were not modified.

### 已覆盖路径

- rafttest InteractionEnv path: capture = InteractionEnv.ProcessReady (existing) retains non-local Ready.Messages in env.Messages and owns continuation; new exact-instance ops TakeMsg/DropMsg/DropMsgs/ClearMessages operate on that same cache; injection on the same cache via DeliverMsg (combined) or TakeMsg + Step (separated) into env.Nodes[To-1]; responses re-enter env.Messages through ProcessReady (exercised by TestInteractionEnvCacheOps).
- RawNode direct drive path: capture = Driver.Ready moves Ready.Messages into the driver-owned MessageCache before delivery and owns continuation; enumeration via Messages/Len; consumption via TakeMsg/DropMsg/DropMsgs/ClearMessages/Deliver; injection via Deliver (combined, test-supplied bind) or TakeMsg + the target RawNode's Step (separated) (exercised by TestDriverCaptureAndDeliver, including vote and append round trips).
- Node channel drive path: capture = the test receives Ready from the n.Ready() channel (single consumer, no racing) and adds rd.Messages to a MessageCache at the capture point, which then owns retention and continuation; enumeration and consumption via the same MessageCache ops; injection is TakeMsg + the owning node's Step (separated form) on that same cache instance.

### 实际实现方式

- added exported exact-instance cache operations on rafttest.InteractionEnv over the existing env-owned in-flight cache env.Messages (TakeMsg, DropMsg, DropMsgs, ClearMessages, Step, DeliverMsg) in rafttest/interaction_env_cache.go
- added an exported standalone MessageCache type (rafttest/message_cache.go) with Add, Len, Messages, TakeMsg, DropMsg, DropMsgs, Clear for message paths that hand Ready.Messages to the caller
- added an exported Driver wrapper (rafttest/driver.go) around *raft.RawNode whose Ready moves Ready.Messages into an owned MessageCache before delivery and whose continuation is owned by the cache until a test action takes, drops, clears, or delivers
- no raft core, Node, RawNode, Ready, or Storage semantics changed; all additions are additive exported APIs in the rafttest package

### 修改前已知限制（供对照）

- Ready.Entries and Ready.CommittedEntries alias the unstable log's backing array until stableTo/applyCommittedEntries; the documented read-only rule on Ready fields is not a safe snapshot for mutation, so capture claims cover Ready.Messages only.
- pb.Message values contain slice fields (Entries, Context, Responses); when a cached message is later stepped into another node, raft log entries alias the message's entry data (append copies struct values but not Data payloads).
- In AsyncStorageWrites mode the local-thread messages (MsgStorageAppend/MsgStorageApply) are captured separately in AppendWork/ApplyWork and their Responses re-enter env.Messages; this remains part of the same rafttest route.

## 消息注入

- 修改前分析状态：`PATCHABLE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：The input mechanics are the genuine protocol boundaries (Step) and rafttest's DeliverMsgs is a real combined call that preserves direction and updates the cache, but exact-instance selection is missing everywhere: on the direct paths Take is hand-written slice surgery, and DeliverMsgs operates on all messages matching a recipient/type pair.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- RawNode direct drive: separated form only — the test removes a message from its caller-owned slice and calls the target's rn.Step(m); targets are the test's RawNode instances, routing from m.To; request/response completion flows back through the target's next Ready.
- Node channel drive: separated form — test takes from its caller-owned slice and calls n.Step(ctx, m); completion via the target's readyc/Advance cycle.
- rafttest InteractionEnv: combined single-call form — DeliverMsgs(typ, Recipient{ID:to}) removes matching messages from env.Messages and steps them into env.Nodes[to-1].Step; Drop variant removes without delivering; cache effects: the entry is removed before Step, and Step errors are written to env.Output.

### Analyzer 建议（修改前）

- Add an exported TakeMsg (exact-instance remove-and-return with routing) to rafttest so the separated form (TakeMsg + node.Step) is complete on the same cache as capture.
- Extend DeliverMsgs (or add DeliverMsg) to accept an exact instance/predicate so the combined single-call form can bind one selected message to its To target, preserving the documented cache effect (removal before Step, error reporting).
- For the direct RawNode/Node paths, add the thin wrapper from the capture suggestion with a Deliver method that performs Take-plus-Step on the same cache, preserving content, destination, and completion.

### 目标已有入口

- `raft.RawNode.Step`
- `raft.Node.Step`
- `rafttest.InteractionEnv.DeliverMsgs`
- `rafttest.InteractionEnv.Stabilize`

### 本次生成接口

- Pending Store：`rafttest/message_cache.go / MessageCache：Same cache as capture: injection removes the selected instance from this cache (or from env.Messages on the env path) and delivers it through the normal protocol input`
- 调用入口：`rafttest/interaction_env_cache.go / InteractionEnv.DeliverMsg：Combined single-call injection on the env path: locates the cached instance, validates the destination against env.Nodes, invokes the normal protocol input (*raft.RawNode).Step, and updates the cache`

### 使用与范围

- 生产路径：Unchanged. All changes are additive exported APIs in the rafttest package; no protocol conditions, messages, destinations, persistence, or recovery behavior modified; the production default is untouched.
- 测试路径：Injection forms exercised by new focused tests in rafttest/message_cache_test.go: combined DeliverMsg round trip (heartbeat request and response through the env cache), combined Driver.Deliver vote/append round trips on the two-node RawNode group, and separated TakeMsg + target.Step delivery with commit advancement. No existing test files were modified.
- 缓存实例引用：The selected cached instance is the target-native raftpb.Message value retained in cache order; DeliverMsg/Driver.Deliver/TakeMsg select it by predicate and the returned message is the exact captured instance with its routing fields. The entry is removed on take/deliver, so a later operation cannot return or deliver a removed instance (stale references are rejected by absence, never silently retargeted). No permanent numeric message IDs are introduced.
- 目标绑定方式：Env path: the destination is resolved from the cached message's To field against env.Nodes (the env-owned registry, the same mapping used by the existing DeliverMsgs); an out-of-range To is rejected before removal and the cache is left unchanged. RawNode direct path: the test owns the node mapping; the combined Driver.Deliver takes a test-supplied bind func(msg) *raft.RawNode that maps and validates To (nil target returns an explicit error and leaves the cache unchanged); the separated form calls the target's Step directly after TakeMsg. Identifier arithmetic is not used as binding; the env registry or the test's own map validates the relationship.
- 缓存变化与失败语义：DeliverMsg/Driver.Deliver (combined): no match -> cache unchanged and ErrNoMessage returned; unknown or unavailable target -> cache unchanged and an explicit error returned; otherwise the entry is removed before Step runs and a synchronous Step error is returned without restoring the entry. Step/TakeMsg (separated): TakeMsg removes the entry and returns it with routing; Step does not touch the cache. Unconfirmed asynchronous delivery does not exist (Step is synchronous); request/response completion is preserved because responses re-enter the same cache through the target's next Ready (ProcessReady on the env path, Ready capture on the driver/MessageCache paths) and are delivered through the same operations. Retry, requeue, duplication, loss, and ordering are tester policy.
- 可选消息 ID 范围：pending_store_instance
- 复制策略：Take/Deliver move the exact retained instance out of the cache (ownership transfer), matching the module's value semantics for pb.Message; no aliasing is introduced between the cache and the delivered message. Enumeration snapshots are deep copies (see message_capture).
- All new entrypoints are externally exported from the go.etcd.io/raft/v3/rafttest package and work in an ordinary non-_test.go import without same-package access.
- The combined form is not transactional: the cache entry is removed before Step runs, and a Step error is returned without restoring it; unknown or unavailable targets are the only case where the cache is left unchanged.
- Injecting a fabricated response instead of the captured instance is not provided and is not a substitute; the cached instance itself enters Step, preserving message direction and content (sender, receiver, and payload).
- The Node channel path uses the separated form only; combined delivery is provided on the RawNode (Driver.Deliver) and env (DeliverMsg) paths, which satisfies the requirement that only one accepted form be complete per path.
- The full module test suite (go test ./...) passes; existing tests were not modified.

### 已覆盖路径

- rafttest InteractionEnv path: capture and injection share env.Messages and the same end-to-end route (ProcessReady -> env.Messages -> DeliverMsg/TakeMsg+Step -> env.Nodes[To-1] -> next Ready -> ProcessReady); both accepted forms are provided (combined DeliverMsg and separated TakeMsg + Step); TestInteractionEnvCacheOps verifies the heartbeat response re-entering the same cache.
- RawNode direct drive path: capture and injection share the driver-owned MessageCache; combined Driver.Deliver (with test-supplied bind) and separated TakeMsg + the target RawNode's Step are both provided; TestDriverCaptureAndDeliver verifies vote, append, and response round trips and commit advancement on both nodes.
- Node channel drive path: capture and injection share the test's MessageCache; the separated form (TakeMsg + the owning node's Step through the documented Node.Step input) is provided, which is sufficient since only one accepted form is required per path.

### 实际实现方式

- completed the separated form on every path: cache TakeMsg removes and returns the exact instance with routing, and the test calls the documented normal protocol input boundary (*raft.RawNode).Step, or env.Step on the env path
- added the combined single-call form on the rafttest env path: InteractionEnv.DeliverMsg locates the cached instance, validates its destination against env.Nodes, steps it through env.Nodes[To-1].Step, and updates the cache
- added the combined single-call form on the RawNode direct path: Driver.Deliver locates the cached instance, binds the target via a test-supplied bind function, steps it through the target's Step, and updates the cache
- injection operates on the same cache instance as capture on every path (env.Messages, the driver-owned MessageCache, or the test's MessageCache), preserving message direction and content

### 修改前已知限制（供对照）

- DeliverMsgs removes the selected cache entries before calling Step; a synchronous Step error does not restore the entry to env.Messages (error is reported to the output buffer instead).
- There is no asynchronous/unconfirmed delivery mode in the library; request/response completion is preserved because responses re-enter the same path through the target's Ready and are delivered via the same cache.
- Injecting a fabricated response instead of the captured instance is not provided for and is not a substitute; the cached instance itself must enter Step.

## 时间控制

- 修改前分析状态：`PATCHABLE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：The protocol time model is a purely logical clock with no wall-clock dependency, and RawNode.Tick plus rafttest Tick provide exact deterministic advances; only the Node-interface Tick is a nonblocking surface that can drop a requested advance, so the Node-driven path is not complete.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- RawNode direct drive: rn.Tick() is a synchronous, deterministic advance; election and heartbeat transitions fire deterministically on the next Ready.
- Node channel drive: n.Tick() posts to a buffered channel consumed by the run loop; exact when the loop keeps up, but drops ticks (with a warning) when the buffer is full, so advances are not guaranteed.
- rafttest InteractionEnv: env.Tick(idx,num) calls RawNode.Tick exactly num times; deterministic advance used by tick-election/tick-heartbeat commands.

### Analyzer 建议（修改前）

- Make Node.Tick lossless: remove the default drop branch (block until the run loop consumes or the node is stopped), preserving the buffered channel for normal operation and keeping production tick ordering and transition conditions.
- Alternatively add a synchronous tick confirmation (e.g. an optional interface with TickAndWait or draining tickc before returning) so the Node path guarantees each requested advance is applied deterministically.
- Keep RawNode.Tick as the documented exact surface and have rafttest Tick continue delegating to it.

### 目标已有入口

- `raft.RawNode.Tick`
- `raft.RawNode.TickQuiesced`
- `raft.Node.Tick`
- `rafttest.InteractionEnv.Tick`

### 本次生成接口

- 调用入口：`node.go / node.Tick：The Node channel-driven logical-clock advance; the modified implementation that now guarantees every tick is accepted by the run loop (lossless).`

### 使用与范围

- 生产路径：Node.Tick blocks until the run loop has accepted the tick or the node has been stopped; the buffered tickc (cap 128) still absorbs bursts, so normal operation is unchanged except that a tick is never dropped (the previous drop-with-warning branch is gone).
- 测试路径：Same code path with no test-only branch: after Tick returns, the advance has been accepted by the run loop and is applied before any later request or observation serviced through the same loop. RawNode.Tick (rawnode.go:64) and rafttest InteractionEnv.Tick (interaction_env_handler_tick.go:34) remain exact synchronous single-tick advances and are unchanged.
- The only production change is removal of the drop branch in node.Tick plus documentation; tickElection/tickHeartbeat, quorum, term, and transition conditions are untouched, so no forbidden protocol semantics changed.
- Blocking cannot starve: a readyc send without a receiver is not a ready select case, so the run loop always services pending ticks even while Ready output is armed; Tick returns promptly on a stopped node via the <-n.done case.
- Existing tests were not modified; the full suite (go test ./...) passes, including TestNodeTick and the rafttest data-driven/network harness tests that drive Node.Tick.
- The removed warning log ('A tick missed to fire') described the drop that no longer occurs.
- Protocol time remains a purely logical clock with no wall-clock dependency; the unexported internal network harness ticker (rafttest/node.go) is out of the protocol-time path and was not changed.
- The tick unit domain is unchanged (unitless logical ticks); no new time values are introduced, so no input-domain validation is needed.
- Exact observation of the applied advance (electionElapsed) requires same-package access, as in the existing TestNodeTick; the new tests are same-package support in package raft, while the consumer-facing surface is the exported Node.Tick.

### 已覆盖路径

- Node channel-driven path: n.Tick() now blocks until the run loop accepts the tick (or the node is stopped), so the requested advance is never dropped; FIFO tickc preserves tick ordering, and the run loop applies each accepted tick (n.rn.Tick()) in the same select case.
- RawNode direct path: RawNode.Tick remains an exact synchronous deterministic single-tick advance (unchanged, rawnode.go:64).
- rafttest InteractionEnv path: env.Tick(idx, num) delegates to RawNode.Tick and remains an exact deterministic advance (unchanged, interaction_env_handler_tick.go:34).

### 实际实现方式

- Removed the nonblocking drop branch from node.Tick (node.go): the select now blocks on the buffered tickc until the node's run loop accepts the tick or the node is stopped (done), so every requested advance is applied and none is silently dropped.
- Documented the lossless guarantee on the public Node interface (node.go) and on the node.Tick implementation; no protocol conditions, timer ordering, or transition logic (tickElection/tickHeartbeat) were changed.
- Added focused same-package tests in a new file node_tick_lossless_test.go exercising the guarantee with a full tick queue and prompt return after Stop; no existing test files were modified.

### 修改前已知限制（供对照）

- Node.Tick drops ticks (with a warning) when 128 ticks are buffered; tests must keep the run loop drained or use RawNode.Tick for guaranteed advances.
- The unexported internal network harness (rafttest/node.go) drives nodes from a real time.Ticker (5ms) and randomized send sleeps; it is same-package-only and its wall-clock behavior is outside the protocol time path.
- Randomized election timeout still determines when a ticked election actually starts (see randomness_control), so exact tick counts do not by themselves manufacture an election outcome.

## 随机性控制

- 修改前分析状态：`PATCHABLE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：The election-timeout draw is protocol-relevant (gates elections), but no externally callable interface exists: the rafttest hook cannot be implemented without internal access, the production source is shared crypto/rand, and the drawn value is not observable, so the test can neither supply nor learn each draw.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- Election timeout randomization (all drive paths): the raft runtime draws randomizedElectionTimeout from globalRand on becoming follower/candidate; the draw determines when tickElection fires MsgHup, so it controls which node becomes candidate and when. Same behavior under RawNode direct drive, Node channel drive, and rafttest env drive.

### Analyzer 建议（修改前）

- Move SetRandomizedElectionTimeout from raft_test.go into production as an exported method on RawNode (rawnode.go), preserving the exact semantics; this makes the rafttest InteractionOpts hook implementable by external consumers and lets the test supply (and therefore know) each draw.
- Alternatively, add a Config-level injection point for the election-timeout draw (e.g. a func(electionTick int) int field or a seedable source) that defaults to the current globalRand behavior, keeping the production default unchanged.
- Document the per-node scope and legal domain: values should remain within [ElectionTick, 2*ElectionTick-1] or be validated as the target validates them.

### 目标已有入口

- `rafttest.InteractionOpts.SetRandomizedElectionTimeout`

### 本次生成接口

- 调用入口：`rawnode.go / RawNode.SetRandomizedElectionTimeout：Exported per-instance override of the randomized election timeout; sets rn.raft.randomizedElectionTimeout directly, exactly like the test-only helper it replaces for external consumers.`

### 使用与范围

- 生产路径：Config.ElectionTimeoutRand == nil (default): resetRandomizedElectionTimeout draws from the shared crypto/rand-backed globalRand source exactly as before; no protocol condition, message, or transition behavior changed.
- 测试路径：With Config.ElectionTimeoutRand set (or the RawNode setter applied), the test supplies and therefore knows every draw; a constant or counter-based function reproduces the same sequence under the same initial state and tick schedule, and the node starts its election at the exact tick implied by the supplied value.
- 缓存实例引用：Per-node scope: Config.ElectionTimeoutRand is copied into the raft runtime at construction (newRaft) and consulted on every draw of that instance; RawNode.SetRandomizedElectionTimeout targets exactly the RawNode instance it is called on. A shared deterministic function across nodes is safe because assignment is per-instance and the function is stateless with respect to instance identity.
- The hook is invoked on every (re-)draw: reset(term) calls resetRandomizedElectionTimeout from becomeFollower, becomeCandidate, and becomeLeader (raft.go:793); the setter only overrides the current draw until the next reset, which the method's doc comment states explicitly.
- Values outside [ElectionTick, 2*ElectionTick-1] are accepted verbatim, exactly like the value produced by the internal draw formula; the target defines no validation for this field, and none was added so the semantics match the pre-existing test-only helper raft.SetRandomizedElectionTimeout (raft_test.go:4098), which remains in place unchanged for the datadriven interaction tests.
- Choice visibility is satisfied by the accepted 'test supplied the value' form; the drawn value is not additionally exposed through Status or Ready.
- The rafttest hook field and its datadriven handler are untouched; only implementability from outside the raft package changed.
- Non-protocol randomness (network drop/delay in the unexported rafttest harness, send-delay sleeps) is outside the protocol boundary and not part of this capability.

### 已覆盖路径

- RawNode direct drive: Config.ElectionTimeoutRand supplies every election-timeout draw, including re-draws on follower/candidate/leader transitions, so election timing is deterministic and each draw is known to the test (it supplied it); RawNode.SetRandomizedElectionTimeout overrides the current draw per instance. Verified by TestElectionTimeoutRandHook (two nodes with draws 10 and 15 start elections at exactly ticks 10 and 15 in lockstep) and TestRawNodeSetRandomizedElectionTimeout (draw 12 fires at exactly tick 12).
- Node channel drive: StartNode/RestartNode both construct the runtime through NewRawNode (node.go:287) so the hook reaches resetRandomizedElectionTimeout on the channel-driven path with no additional code.
- rafttest InteractionEnv: env.AddNodes applies OnConfig to each node's Config before NewRawNode, so ElectionTimeoutRand is installable for env-created nodes; the existing exported InteractionOpts.SetRandomizedElectionTimeout hook is now implementable externally through the RawNode method expression. Verified by TestInteractionEnvSetRandomizedElectionTimeoutHook, which also compile-checks the method-expression signature.

### 实际实现方式

- inject_dependency: added an optional per-node draw hook Config.ElectionTimeoutRand func(electionTick int) int, consulted by resetRandomizedElectionTimeout instead of the global crypto/rand-backed source when non-nil; production default (nil) is unchanged
- add_test_configuration: wired the hook from Config through newRaft into the raft runtime so every (re-)draw on every drive path (RawNode, Node, rafttest) is supplied by the test and therefore known to it
- add_test_only_wrapper: added exported method RawNode.SetRandomizedElectionTimeout(timeout int) that preserves the exact semantics of the long-standing test-only helper (raft_test.go:4098), making rafttest's existing exported InteractionOpts.SetRandomizedElectionTimeout hook implementable by external consumers via the method expression

### 修改前已知限制（供对照）

- Non-protocol randomness (network drop/delay in the unexported rafttest/network.go harness, send-delay sleeps in rafttest/node.go) is out of the protocol boundary or setup-only and is not counted.
- The draw value is not exposed by Status/BasicStatus/Ready, so without a setter the test cannot learn the selected value before scheduling dependent work.
- Randomization is reset on every follower/candidate transition; reproducible control must cover each reset.

## 生命周期控制

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Both crash (discard the volatile runtime object, retain only what was written to the Storage implementation) and restart (NewRawNode/RestartNode on the same Storage) are directly usable compositions of existing public operations on all three paths; the testing contract explicitly does not require a convenience wrapper.

### Analyzer 发现的实现路径（修改前）

- RawNode direct drive: crash = drop the RawNode reference keeping the *MemoryStorage; restart = NewRawNode(cfg with same cfg.Storage), fresh runtime restored from InitialState().
- Node channel drive: crash = n.Stop() and discard the Node; restart = RestartNode(c) with the same MemoryStorage, spawning a fresh run loop.
- rafttest InteractionEnv: crash = discard env.Nodes[i].RawNode while keeping the exported Node.Storage; restart = NewRawNode(&cfg) with the same storage assigned back to env.Nodes[i].RawNode (all fields exported).

### 目标已有入口

- `raft.NewRawNode`
- `raft.RestartNode`
- `raft.StartNode`
- `raft.Node.Stop`
- `raft.MemoryStorage`
- `rafttest.Node.RawNode`
- `rafttest.Node.Storage`
- `rafttest.Node.Config`
- `rafttest.InteractionEnv.AddNodes`

### 当前限制

- There is no dedicated crash/restart helper in rafttest; rafttest/interaction_env_handler_process_ready.go:46 has a 'TODO(tbg): Allow simulating crashes here', so the env path is a manual composition using exported fields.
- MemoryStorage is in-memory only; real WAL/disk durability is outside the system boundary, so durability is whatever the target Storage implementation provides.
- Catch-up after restart (re-replicating committed entries, responding to MsgApp) is protocol behavior the test drives and observes, not behavior implemented by the seam.
- Pause/resume, disconnect, and message-loss primitives exist only in the unexported internal network harness (rafttest/node.go, rafttest/network.go) for same-package tests; they are not exported crash facilities.

## 状态观察

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Status/BasicStatus are documented public accessors that deep-copy the claimed minimum state (role, term, commit, applied, lead, progress, config), so no new target code is needed for observation on any path; rafttest handlers are thin wrappers over the same snapshot-safe data.

### Analyzer 发现的实现路径（修改前）

- RawNode direct drive: rn.Status()/rn.BasicStatus()/rn.WithProgress() expose role, term, commit, applied, lead, and leader progress as snapshot-safe values.
- Node channel drive: n.Status() routes to getStatus on the raft goroutine and returns the same deep-copied Status.
- rafttest InteractionEnv: env.Status(idx) and handleRaftState print Status-derived state; env.RaftLog(idx) reads the retained Storage for log-range observation.

### 目标已有入口

- `raft.RawNode.Status`
- `raft.RawNode.BasicStatus`
- `raft.RawNode.WithProgress`
- `raft.Node.Status`
- `rafttest.InteractionEnv.Status`
- `rafttest.InteractionEnv.RaftLog`
- `raft.MemoryStorage.Entries`
- `raft.MemoryStorage.FirstIndex`
- `raft.MemoryStorage.LastIndex`

### 当前限制

- MemoryStorage.Entries (and hence rafttest RaftLog) returns slices whose element fields (e.g. Data) still alias the storage's entries; the documented 'must not mutate' rule is not element-level snapshot isolation. Log-range observation is therefore a weaker primitive than Status and is excluded from the positive snapshot-safety claim.
- Randomized election timeout and pending-conf-change internals are not exposed by Status; they are not part of the claimed observation set.
- The Progress map is only populated on the leader (getStatus), matching the documented Status contract.

## 外部输入

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Propose/ProposeConfChange/ReadIndex are documented public methods on both Node and RawNode, and rafttest exposes exported Propose/ProposeConfChange handlers; no new target code is required for the declared consumer to submit application work.

### Analyzer 发现的实现路径（修改前）

- RawNode direct drive: test calls rn.Propose/rn.ProposeConfChange/rn.ReadIndex; proposal becomes a local MsgProp/MsgReadIndex stepped into r.raft.Step and appears in Ready output.
- Node channel drive: test calls n.Propose/n.ProposeConfChange/n.ReadIndex; run loop forwards via propc/recvc and steps into the same raft state machine.
- rafttest InteractionEnv: test calls env.Propose(idx,data)/env.ProposeConfChange(idx,cc); delegates to the embedded RawNode of the env-owned node.

### 目标已有入口

- `raft.RawNode.Propose`
- `raft.RawNode.ProposeConfChange`
- `raft.RawNode.ReadIndex`
- `raft.Node.Propose`
- `raft.Node.ProposeConfChange`
- `raft.Node.ReadIndex`
- `rafttest.InteractionEnv.Propose`
- `rafttest.InteractionEnv.ProposeConfChange`

### 当前限制

- Peer protocol messages (MsgApp, MsgVote, MsgHeartbeat, MsgSnap and their responses) entering via Step are protocol ingress, not application workload; excluded per obligation.
- Campaign, TransferLeadership, ForgetLeader, Compact, SendSnapshot, ReportUnreachable and ReportSnapshot are leadership/maintenance/diagnostic operations and are excluded from the workload claim.
- Proposals may be dropped (ErrProposalDropped) or lost without notice; retry is tester policy as documented in Node.Propose.
- Real networking and application state-machine ingestion are outside the system boundary.
