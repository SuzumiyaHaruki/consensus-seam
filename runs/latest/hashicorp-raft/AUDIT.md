# hashicorp-raft 测试接口审计报告

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
Analyzer 内容描述修改前状态；生成接口和 Reviewer 内容描述候选修改后状态。
机器可读细节以`capability-report.json`为准。

## 消息捕获

- 修改前分析状态：`PATCHABLE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：No controlled capture cache exists for any path: InmemTransport.consumerCh is consumed exclusively by the raft loop selected on r.rpcCh (api.go:561), and the transport internals are unexported, so a test cannot enumerate, take, drop, or clear messages without racing the protocol consumer. The RPC type and Transport interface are complete building blocks, but no target API provides the cache, so capture must be built as a harness-side transport.

### Analyzer 发现的实现路径（修改前）

- append_entries (incl. heartbeat and pipelined AppendEntries): leader replicate/heartbeat -> Transport.AppendEntries -> target inbound queue -> raft rpcCh -> processRPC -> appendEntries (raft.go:1397-1398, 1440)
- request_vote (incl. pre-vote): candidate electSelf/preElectSelf -> Transport.RequestVote/RequestPreVote -> raft rpcCh -> processRPC -> requestVote (raft.go:1399-1402, 1603)
- install_snapshot: leader snapshot push -> Transport.InstallSnapshot -> raft rpcCh -> processRPC -> installSnapshot (raft.go:1403-1404, 1814)
- timeout_now: leadership transfer -> Transport.TimeoutNow -> raft rpcCh -> processRPC -> timeoutNow (raft.go:1405-1406, 2209)

### Analyzer 建议（修改前）

- Implement a test-side Transport (harness extension; the pattern is proven by the module's own fuzzy/transport.go, outside the boundary): expose a test-owned inbound RPC queue, return it from Consumer(), withhold delivery to raft and withhold RespChan responses, and provide Enumerate/Take/Drop/Clear/Deliver operations.
- Alternatively add a small package-level controlled transport as a new file implementing the existing Transport interface; no core-loop changes are required.
- Capture responses at the same transport boundary before returning them to the blocked sender (InmemTransport makeRPC waits on respCh at inmem_transport.go:191-198), and release them on test action so the original completion mechanism is preserved.

### 目标已有入口

- `Transport interface methods and Consumer() channel (existing primitives)`
- `Harness-defined controlled transport: Enumerate/Take/Drop/Clear/Deliver (proposed, no target core changes)`

### 当前限制

- Real network transports (net_transport.go, tcp_transport.go) are outside the system boundary.
- InstallSnapshot carries a streaming io.Reader (RPC.Reader); the harness must retain or copy the stream while the message is captured.
- The module's in-process test support (testing.go) provides MockFSM/InmemStore/InmemSnapshotStore but no message-control cache.
- A capture cache implemented with the InmemTransport itself is impossible without target changes because the consumer channel is internal and raft is its exclusive consumer.

## 消息注入

- 修改前分析状态：`PATCHABLE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：There is no existing API to deliver a concrete message into a running node's protocol input: rpcCh is bound to trans.Consumer() and InmemTransport exposes no ingress method, so injection is only possible through a test-owned transport that forwards the selected RPC into the Consumer() channel. Fabricating messages without the capture cache is only a primitive, not complete injection.

### Analyzer 发现的实现路径（修改前）

- append_entries (incl. heartbeat and pipelined AppendEntries): captured AppendEntriesRequest forwarded into target's Consumer() channel -> processRPC -> appendEntries; response released via RespChan to the waiting leader
- request_vote (incl. pre-vote): captured RequestVote/RequestPreVote forwarded -> processRPC -> requestVote; response released via RespChan to the waiting candidate
- install_snapshot: captured InstallSnapshotRequest (with Reader stream) forwarded -> processRPC -> installSnapshot
- timeout_now: captured TimeoutNowRequest forwarded -> processRPC -> timeoutNow (raft.go:2209-2214)

### Analyzer 建议（修改前）

- Separated form: cache.Take(selected) returns the RPC (Command + RespChan + Reader) and the test pushes it into that target's Consumer() channel; the test already owns the target mapping.
- Combined form: transport.Deliver(target, rpc) locates/validates the target node transport and performs the forward, updating cache state in the same call (no transactional atomicity implied).
- Declare cache effects explicitly: successful delivery removes the entry and returns the handler's response to the blocked sender; synchronous rejection (rpc.Respond(nil, err), raft.go:1391-1394) also removes it with the error propagated; unconfirmed asynchronous delivery leaves retry/requeue/duplication as tester policy.
- Preserve direction and completion: inject the captured request through processRPC for its own message type; a response is injected only when the selected cached instance is that response, released to the waiting sender's respCh.

### 目标已有入口

- `Harness-defined controlled transport Deliver/input operations (proposed, combined single-call or separated Take-plus-input)`

### 当前限制

- Injection through the InmemTransport itself is impossible for a running raft because its consumer channel is unexported and raft is the exclusive consumer.
- TimeoutNow/InstallSnapshot streams and leadership-transfer responses must be handled by the harness transport like any other RPC; no target API exists for them either.
- Real TCP/network transports are outside the boundary.

## 时间控制

- 修改前分析状态：`INVASIVE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：No Clock or Tick abstraction exists anywhere in the module; all protocol timing is dispersed wall-clock use (randomTimeout -> time.After for election/heartbeat/commit/snapshot staggering, leader-lease timers, replication backoff, time.Now last-contact tracking). There is no single seam a test can advance deterministically.

### Analyzer 建议（修改前）

- Introduce an injectable clock (e.g. Config.Clock exposing Now/After/Timer) and route the protocol timers in raft.go, replication.go, snapshot.go, and log.go through it; this is a core restructuring across the state loops, hence INVASIVE for v0.1.
- Short of that, tests may only scale timeouts (HeartbeatTimeout/ElectionTimeout/CommitTimeout, config.go:149-161) and wait in wall-clock time; this controls scale, not determinism.

### 可参考的源码位置

- `util.go:34`：Election/heartbeat/commit/snapshot timers are created with time.After (util.go:39); no Clock or Tick abstraction exists anywhere in the module.
- `raft.go:163`：Follower heartbeat timer (also election timer raft.go:310, leader lease raft.go:677/947, time.Since last-contact check raft.go:221) uses real wall-clock time.
- `replication.go:402`：Heartbeat interval and commit staggering use randomTimeout; backoff waits use time.After (replication.go:213, 419) and last-contact uses time.Now (replication.go:131).
- `snapshot.go:75`：Snapshot-interval timer uses randomTimeout over the real clock.

### 当前限制

- Caller-side deadlines (Apply/AddVoter/Barrier timeouts, api.go:829-831, 861-863) are caller-side API deadlines, not protocol-time paths.
- Transport RPC timeouts (inmem_transport.go:185, 196) are transport-side and outside the protocol loops.
- AppendedAt (log.go:96-107) is explicitly informational and not used for coordination, so it is not a protocol-time path.

## 随机性控制

- 修改前分析状态：`PATCHABLE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：randomTimeout draws from the package-global math/rand seeded once in init() (util.go:18-21, 34-40); there is no config knob, injected source, or hook. A test calling rand.Seed cannot pin choices per node because concurrent raft goroutines (several nodes' main loops, replication loops, snapshot loop) race for values from the shared generator, so reproducible per-instance assignment is impossible as exposed.

### Analyzer 建议（修改前）

- Add an optional Rand *rand.Rand field to Config; add a r.randomTimeout(d) helper that uses r.config().Rand when set and falls back to the global rand when nil, preserving the production default unchanged.
- Replace the randomTimeout call sites (raft.go:163, 217, 310, 353, 426; replication.go:169, 402, 495; snapshot.go:75) with the helper.
- Tests inject per-node sources, e.g. rand.New(rand.NewSource(seed)), via Config for each node so the same seed reproduces the same per-node choices.

### 目标已有入口

- `Config.Rand *rand.Rand (proposed injectable per-node source)`

### 当前限制

- NewInmemAddr/generateUUID (inmem_transport.go:15-17, util.go:58-71) use crypto/rand for addresses; these are setup IDs, not protocol decisions, and are excluded from the capability scope.
- Randomness control alone does not make elections fully deterministic: wall-clock timing (time.After) still governs when timers fire, so pairing with time control is required for full determinism.

## 生命周期控制

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Shutdown plus reconstruction over the caller-owned stores composes directly into a full availability cycle; the testing contract explicitly allows a directly usable composition and no convenience wrapper is required.

### Analyzer 发现的实现路径（修改前）

- stop: Raft.Shutdown() closes shutdownCh, sets state Shutdown; shutdownFuture.Error() waits on waitShutdown for all protocol goroutines to exit and closes the transport if it implements WithClose
- restore: NewRaft(conf, fsm, logs, stable, snaps, trans) reconstructs the logical node over the same caller-owned stores, replaying snapshot/log/stable state via restoreSnapshot

### 目标已有入口

- `Raft.Shutdown`
- `shutdownFuture.Error`
- `NewRaft`

### 当前限制

- The cycle is honest stop + reconstruction: Shutdown is terminal for that instance and the restored node is a NEW instance over the same stores; there is no pause/resume and no crash/persistence simulation.
- InmemTransport.Disconnect/DisconnectAll/Connect (inmem_transport.go:214-251) only remove network routes while the node keeps running its protocol loops; a partition alone is not lifecycle unavailability.
- shutdownFuture.Error() closes the transport when it implements WithClose (future.go:176-178), so the transport must be recreated or reconnected for the next cycle.

## 状态观察

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Raft exposes target-native accessors for role, term, commit/applied index, last log, leader, and configuration, and the log/stable/snapshot state is readable through the caller-owned store objects. Together these cover the minimum claimed state (role, term, commit_index, applied_index, log_range) with no new target code; the returned values are strings, scalars, or deep-copied configurations.

### Analyzer 发现的实现路径（修改前）

- node status: synchronous accessors on *Raft backed by raftState atomics (state/term/commit/applied/last-log/last-contact/leader)
- configuration: GetConfiguration() -> configurationsFuture.Configuration()/Index() (async future completion surface)
- caller-owned stores: log range and stable term/voted-for read through the InmemStore the test passed to NewRaft; snapshots through InmemSnapshotStore.List

### 目标已有入口

- `Raft.State / Raft.Stats / Raft.CurrentTerm / Raft.CommitIndex / Raft.AppliedIndex / Raft.LastIndex / Raft.LastContact / Raft.LeaderWithID`
- `Raft.GetConfiguration (ConfigurationFuture)`
- `InmemStore.FirstIndex/LastIndex/GetLog/GetUint64 and InmemSnapshotStore.List (caller-owned stores)`

### 当前限制

- InmemStore.GetLog copies the Log struct but shares the Data/Extensions byte slices with the stored entry (inmem_store.go:56); callers should treat log payloads as read-only (shallow-copy caveat).
- Stats values are formatted strings derived at call time; leader notifications also exist via LeaderCh/NotifyCh but are not needed for the minimum interface.
- LogCache (log_cache.go) and FileSnapshotStore are additional primitives; FSM application state is application-owned and outside the boundary.

## 外部输入

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Both application workload classes are directly callable public methods returning typed futures (ApplyFuture, IndexFuture); no target code is required to submit proposals or membership changes.

### Analyzer 发现的实现路径（修改前）

- proposal: Raft.Apply/ApplyLog -> applyCh -> leaderLoop (applyCh case) -> dispatchLogs -> LogStore append + commitment -> FSM apply -> ApplyFuture completes
- membership change: AddVoter/AddNonvoter/RemoveServer/DemoteVoter -> configurationChangeCh -> leaderLoop (configurationChangeChIfStable) -> LogConfiguration append/commit -> IndexFuture completes

### 目标已有入口

- `Raft.Apply / Raft.ApplyLog`
- `Raft.AddVoter / Raft.AddNonvoter / Raft.RemoveServer / Raft.DemoteVoter`

### 当前限制

- Barrier, VerifyLeader, Snapshot, Restore, BootstrapCluster, LeadershipTransfer, and the deprecated AddPeer/RemovePeer are control or maintenance operations and are excluded from the workload scope.
- Application reads are not replicated protocol operations in this library; FSM read semantics are application-owned and outside the boundary.
- A proposal or membership change submitted to a non-leader fails with ErrNotLeader (raft.go:176-196); the library does not forward client requests to the leader.
