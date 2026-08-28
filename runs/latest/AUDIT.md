# hashicorp-raft 测试接口审计报告

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
Analyzer 内容描述修改前状态；生成接口和 Reviewer 内容描述候选修改后状态。
机器可读细节以`capability-report.json`为准。

## 消息捕获

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Transport abstraction, InmemTransport, RPC struct, and observer mechanism inside the boundary; real network transports outside.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：Existing primitives (Transport interface, RPC/RespChan, InmemTransport consumer channel, observers) allow a test to see messages only by replacing the transport (a caller-created collection, i.e. a primitive) or by reading post-processing notifications; no complete capture cache with continuation ownership and Take/Drop/Clear exists in the target.

### Analyzer 发现的实现路径（修改前）

- inbound-consumer: requests arrive at a node via Transport.Consumer(); Raft stores the channel as rpcCh (api.go:561) and the main loop is the sole consumer (raft.go:169,323,683), dispatching in processRPC (raft.go:1390); responses complete the original exchange through RPC.RespChan (transport.go:18-27). Heartbeats are AppendEntries with empty entries on the same channel for InmemTransport (SetHeartbeatHandler is a no-op, inmem_transport.go:72-75); a fast-path handler exists as a separate control surface for transports that support it.
- outbound-send: synchronous Transport.AppendEntries (replication.go:231,412), RequestVote/RequestPreVote, InstallSnapshot, TimeoutNow calls; each returns by copying into a caller-owned response value; a test-visible capture point would sit at these methods, holding the call until the test takes/drops/clears/injects.
- outbound-pipeline: Transport.AppendEntriesPipeline (replication.go:452) returns an AppendPipeline whose AppendEntries returns an AppendFuture with its own Consumer() channel (transport.go:112-123; inmem_transport.go:259-309); completion is asynchronous via future.respond.

### Analyzer 建议（修改前）

- Add a small in-package capture transport (e.g., raft.testCaptureTransport wrapping any Transport) that owns the Consumer() channel so the capture point is the protocol consumer, and queues outbound AppendEntries/RequestVote/InstallSnapshot/TimeoutNow/pipeline calls with target routing; expose Enumerate/Take/Drop/Clear on the queue.
- Alternatively add an opt-in capture mode to InmemTransport (a replaceable consumer channel plus outbound queues) while keeping the default path unchanged.
- Expose an in-package wrapper for AppendPipeline that records AppendFuture completion so the outbound-pipeline path is captured with the same cache semantics.

### 目标已有入口

- `Transport.Consumer() inbound channel (transport.go:34)`
- `Transport.AppendEntries / RequestVote / InstallSnapshot / TimeoutNow / RequestPreVote (transport.go:44-66, 74-77)`
- `Transport.AppendEntriesPipeline (transport.go:41, 112-123)`
- `Transport.SetHeartbeatHandler (transport.go:59-63)`
- `Observer/RegisterObserver (observer.go:106-118)`

### 当前限制

- InmemTransport.AppendEntries/RequestVote block the sender until a response or 500ms timeout (inmem_transport.go:166-200); a capture point that holds inbound RPCs must eventually respond through RPC.Respond or the sender observes a timeout.
- RPC does not carry the sender address; routing info for inbound messages must be read from the request's RPCHeader (ID/Addr, raft.go:35-41).
- If a transport uses SetHeartbeatHandler for a heartbeat fast-path, capture must also hook that handler; InmemTransport ignores it.
- Responses are not separate cacheable messages: they complete the original RPC via RespChan or the pipeline future and cannot be captured as independent instances.

## 消息注入

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Same message-control boundary and path partition as message_capture.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：The Transport seam plus RPC.RespChan are the underlying plumbing: they make injection possible in principle, but there is no target-side cache to Take from and no complete injection interface, so a harness/package addition is required.

### Analyzer 发现的实现路径（修改前）

- inbound-consumer: normal input boundary is the channel returned by Transport.Consumer(), drained by the Raft main loop (raft.go:169,323,683) and dispatched by processRPC/processHeartbeat (raft.go:1390-1436); injection means delivering a captured request RPC (with its RespChan) onto that owned channel, preserving direction and the response completion mechanism
- outbound-send: normal input boundary is the Transport send method for the message's own direction (AppendEntries at replication.go:231,412; RequestVote/RequestPreVote; InstallSnapshot; TimeoutNow); a captured outbound request is injected by invoking the real transport's method with the captured args, target, and response pointer
- outbound-pipeline: normal input boundary is AppendPipeline.AppendEntries (transport.go:115); injection preserves the AppendFuture completion (inmem_transport.go:311-339)

### Analyzer 建议（修改前）

- With the proposed capture transport, provide Take(target) that removes and returns the selected message plus routing (peer address; inbound RPCHeader), and a documented normal input call per path: enqueue onto the owned consumer channel for inbound, invoke the underlying transport method for outbound-send, invoke AppendPipeline for outbound-pipeline.
- Optionally provide a combined single-call facade on the capture transport: Take + validate target + invoke normal input + update cache state in one method (without implying atomicity).
- Define and document cache effects for success (entry removed), synchronous failure (entry removed with error surfaced), and unconfirmed async delivery (entry removed or retained by explicit policy).

### 目标已有入口

- `RPC.Respond (transport.go:25-27)`
- `Transport consumer channel (injection target for inbound requests)`
- `Transport send methods and AppendPipeline (injection targets for outbound requests)`
- `processRPC / processHeartbeat dispatch inside Raft (raft.go:1390-1436)`

### 当前限制

- Cache effects for synchronous failure (sender-side timeout) and unconfirmed async delivery (pipeline inflight) must be defined by the harness transport; the target defines none.
- Injecting an inbound request whose sender already timed out leaves a dangling RespChan send unless the harness completes it (transport.go:25-27).
- Fabricating or completing a response does not count as injecting a cached request; only a cached response instance may enter a response boundary, and in this codebase responses complete the original RPC rather than forming an independent inbound path.

## 时间控制

- 修改前分析状态：`INVASIVE`
- 覆盖边界：Protocol loops, replication, and snapshot scheduling inside the raft module.
- 修改前测试接口是否完整：否
- 修改前测试支持判断：Only wall-clock duration configuration exists; no Tick or Clock abstraction is exposed, so the existing interface is not a complete deterministic time-control interface.

### Analyzer 发现的实现路径（修改前）

- election/heartbeat timers: randomTimeout builds time.After channels (raft.go:163,217,310,353,426)
- commit timer: randomTimeout(CommitTimeout) in replication loops (replication.go:169,495)
- snapshot check timer: randomTimeout(SnapshotInterval) (snapshot.go:75)
- user-API timeouts: time.After in Apply/Barrier/Restore/requestConfigChange (api.go:831,861,1058; raft.go:117-119)
- wall-clock observations: time.Now/time.Since for lastContact staleness (raft.go:221, api.go:1128-1132, 1215)

### Analyzer 建议（修改前）

- Introduce an injectable clock (interface with Now() and After()) threaded into Raft and its Config, replacing direct time.After/time.Now/time.Since in raft.go, replication.go, snapshot.go, future.go, and api.go timeout paths.
- Alternatively expose an explicit Tick/step mechanism on the main loop, converting timer channels into tick counters — a larger structural change affecting runFollower/runCandidate/runLeader.

### 目标已有入口

- `time.After / time.NewTimer usage: util.go:39 (randomTimeout), api.go:831,861,1058 (Apply/Barrier/Restore timeouts), raft.go:163-353 (heartbeat/election), replication.go:169,402,495, snapshot.go:75`
- `time.Now / time.Since: api.go:1128 (LastContact), api.go:1215 (Stats), raft.go:221 (contact check), future.go:135 (dispatch), replication.go:416 (LastContact observation)`
- `Config.HeartbeatTimeout / ElectionTimeout / CommitTimeout / LeaderLeaseTimeout / SnapshotInterval (config.go:149-205) with ReloadConfig (api.go:717-741)`

### 当前限制

- randomTimeout randomizes every interval to [minVal, 2*minVal) (util.go:33-40), so even configured durations are jittered and non-deterministic.
- Config validation enforces minimums (HeartbeatTimeout >= 5ms, ElectionTimeout >= HeartbeatTimeout, CommitTimeout >= 1ms; config.go:348-374), limiting how small a test may set timers.
- BatchApplyCh buffers applyCh to MaxAppendEntries and can break CommitTimeout guarantees (config.go:169-174).

## 随机性控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Protocol-internal randomness in the raft module (election timeout jitter, commit/snapshot staggering, in-memory address generation).
- 修改前测试接口是否完整：否
- 修改前测试支持判断：Only a package-global seeded source exists; there is no test-visible injection point, so the existing interface is a primitive for reproducible per-instance choices.

### Analyzer 发现的实现路径（修改前）

- election/heartbeat jitter: rand.Int63() draws from the process-global math/rand source seeded once in init() (util.go:18-40); each node's goroutines call randomTimeout concurrently
- commit and snapshot staggering: same global source (replication.go:169,495; snapshot.go:75)
- address generation: crypto/rand, not seeded (inmem_transport.go:15-17)

### Analyzer 建议（修改前）

- Add a Config field such as `ElectionTimeoutRandomization func(minVal time.Duration) time.Duration` (or an injectable *rand.Rand) stored in the atomic Config and used by every randomTimeout call site; keep the current global-rand behavior as the default.
- Thread the same injected source through replication.go and snapshot.go staggering so the whole timing domain is controlled consistently.

### 目标已有入口

- `randomTimeout (util.go:34) used at raft.go:163, 217, 310, 353, 426; replication.go:169, 402, 495; snapshot.go:75`
- `package init seeding of global math/rand (util.go:18-21)`
- `NewInmemAddr / generateUUID (inmem_transport.go:15-17, util.go:59-71)`

### 当前限制

- NewInmemAddr and generateUUID use crypto/rand (inmem_transport.go:15-17; util.go:59-71) and are not reproducible; they do not affect protocol decisions but do affect addresses.
- randomTimeout(0) returns nil (no timer) — any injected source must preserve this sentinel behavior (util.go:35-37).
- Snapshot interval staggering also draws from the same source (snapshot.go:75); the control mechanism should cover all randomTimeout call sites for a coherent domain.

## 生命周期控制

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Public Raft API and in-process stores (InmemStore/InmemSnapshotStore/FileSnapshotStore) inside the boundary; process supervision and external durable store implementations outside.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Shutdown() and NewRaft() are directly usable public operations; no new target code is needed to make a node unavailable and bring it back as the same logical node.

### Analyzer 发现的实现路径（修改前）

- stop: Shutdown() closes shutdownCh (set in api.go:1017), sets state Shutdown (api.go:1019); run/runFSM/runSnapshots goroutines exit on <-shutdownCh (raft.go:139,252,436,683); shutdownFuture.Error waits via waitShutdown and closes the transport when it implements WithClose (future.go:167-180)
- restore: new *Raft built over the same caller-owned LogStore/StableStore/SnapshotStore/FSM with the same LocalID resumes protocol activity; NewRaft replays snapshot + log configuration entries (api.go:592-625); restart pattern used by the package's own tests (raft_test.go:1004, 2788)
- network partition (not lifecycle): InmemTransport Connect/Disconnect/DisconnectAll (inmem_transport.go:214-251) isolate peers while the node keeps running local protocol loops

### 目标已有入口

- `Raft.Shutdown (api.go:1012)`
- `Raft.NewRaft reconstruction (api.go:500)`
- `cluster.Close / shutdown helpers in package testing support`

### 当前限制

- No pause/resume exists; Shutdown is terminal for the instance and closes a WithClose transport (future.go:176-178), so the test must supply a fresh or reconnected transport on reconstruction.
- Persistence of term/vote/log across the cycle depends on the caller's store implementations (InmemStore is volatile in-process).
- Network isolation alone (Disconnect) does not stop local protocol activity and is therefore not lifecycle unavailability.

## 状态观察

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Public Raft accessors, observer API, and caller-owned stores inside the boundary.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：State(), Stats(), index accessors, LeaderWithID, GetConfiguration, LastContact, LeaderCh, and the observer API are directly usable public interfaces; no target code is required for observation.

### Analyzer 发现的实现路径（修改前）

- scalar node state: State/CurrentTerm/LastIndex/CommitIndex/AppliedIndex read atomics or locks (state.go:79-110; api.go:1102-1247)
- aggregate snapshot: Stats builds a fresh map[string]string from atomics plus GetConfiguration (api.go:1160-1218)
- configuration: GetConfiguration returns the cloned atomic copy of the latest configuration (raft.go:2220-2241; configuration.go:83-86)
- event stream: Observer channel receives Observation{Raft: *Raft, Data: ...} for RequestVoteRequest, state changes, peer/leader changes, heartbeat failures (observer.go:120-149; raft.go:108, 614, 1605, 1738, 2157)
- log range: the test reads the caller-provided LogStore (e.g., NewInmemStore) directly

### 目标已有入口

- `Raft.State (api.go:1102)`
- `Raft.Stats (api.go:1160)`
- `Raft.CurrentTerm / LastIndex / CommitIndex / AppliedIndex (api.go:1221-1247)`
- `Raft.LeaderWithID / Leader / LastContact / LeaderCh (api.go:786-802, 1128, 1117)`
- `Raft.GetConfiguration (api.go:897) and ConfigurationFuture`
- `Raft.ReloadableConfig (api.go:749)`
- `NewObserver / RegisterObserver / DeregisterObserver (observer.go:87-118)`
- `caller-owned LogStore for log ranges (LogStore.GetLog/FirstIndex/LastIndex, log.go)`

### 当前限制

- GetConfiguration/ConfigurationFuture return a Configuration whose Servers slice shares its backing array with the stored atomic copy (configuration.go:83-86 plus api.go:897-902): caller mutation of the returned slice corrupts subsequent reads of that copy, so it is not a fully deep snapshot (protocol main-loop state is unaffected).
- Stats documents itself as informational/debug-only (api.go:1135-1136) and 'applied_index' may lag the FSM's actual consumption (api.go:1240-1244).
- Observer channels are non-blocking by default and drop observations when full (observer.go:140-146).

## 外部输入

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Public Raft API of the pinned github.com/hashicorp/raft module (Raft methods, Transport abstraction, InmemTransport, observer/future mechanisms, module-provided in-memory stores). Real TCP transports, external durable stores, application FSM semantics, and fuzzy/raft-compat/bench trees are outside.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The existing public API directly provides all workload entrypoints and blocking completion futures; a test cluster (MakeCluster/MakeClusterCustom, testing.go:733-858) plus leader.Apply/AddVoter suffices with no additional target code.

### Analyzer 发现的实现路径（修改前）

- proposal: Raft.Apply/ApplyLog -> applyCh -> leader main loop appends LogCommand -> commit -> fsmMutateCh -> FSM.Apply; completion via ApplyFuture.Error/Index/Response
- membership: AddVoter/AddNonvoter/RemoveServer/DemoteVoter -> requestConfigChange -> configurationChangeCh -> LogConfiguration entry -> commit -> ConfigurationStore.StoreConfiguration
- rejected-on-follower: applyCh/configurationChangeCh are answered ErrNotLeader in runFollower/runCandidate (raft.go:173-196, 386-394)

### 目标已有入口

- `Raft.Apply (api.go:819)`
- `Raft.ApplyLog (api.go:826)`
- `Raft.AddVoter / AddNonvoter / RemoveServer / DemoteVoter (api.go:946-1007)`
- `Raft.AddPeer / RemovePeer deprecated (api.go:908-936)`

### 当前限制

- Apply returns ErrLeadershipLost if leadership is lost mid-apply; whether the write survived is unknowable by design (api.go:810-814).
- Future.Error() must be called before Future.Index()/Response()/Configuration() (future.go:13-65).
- GetConfiguration, Barrier, and VerifyLeader can block forever if enqueued concurrently with shutdown (raft_test.go:40-42 documents this known quirk).
