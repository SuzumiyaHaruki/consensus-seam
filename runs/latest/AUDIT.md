# hashicorp-raft 测试接口审计报告

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
Analyzer 内容描述修改前状态；生成接口和 Reviewer 内容描述候选修改后状态。
机器可读细节以`capability-report.json`为准。

## 消息捕获

- 修改前分析状态：`PATCHABLE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：The consumer channel is a primitive under the contract: it is an observable channel shared with the protocol consumer, so guaranteed retention-before-delivery, explicit Take/Drop/Clear operations, and external requeue of captured requests are not provided by the target API; only the raw intercept mechanics exist (proven by transport_test.go and inmem_transport_test.go).

### Analyzer 发现的实现路径（修改前）

- inbound_rpc: per-node InmemTransport consumerCh. Protocol output: RPC requests from peers (RequestVote, RequestPreVote, AppendEntries incl. heartbeats, InstallSnapshot, TimeoutNow) enqueued via makeRPC; delivery to the node automatically continues when the main loop reads rpcCh, and is paused whenever the test holds a taken RPC (the sender blocks on RespChan). Cache owner: the InmemTransport instance (channel buffer, cap 16). Enumerate: drain with select/default; Take: receive one RPC; Drop: receive and ignore or Respond(err); Clear: drain loop. Normal input boundary: trans.Consumer() -> rpcCh -> processRPC. Consumer scope: any test holding the *InmemTransport (public Consumer()); in-package tests additionally reach the private field. Injection pairing: separated Take plus Respond/requeue; no combined single-call facade.
- append_pipeline: pipelined AppendEntries from a leader replication loop. Requests traverse the same peer consumerCh capture point (inmemPipeline.AppendEntries enqueues an RPC there), so capture is identical to inbound_rpc; responses are decoded by inmemPipeline.decodeResponses into the pipeline's doneCh (pipeline.Consumer() -> <-chan AppendFuture). A test intercepting at the peer's consumerCh controls both the request and its response via rpc.Respond.

### Analyzer 建议（修改前）

- Add an exported intercepting/capture transport (or a testing.go helper) that drains InmemTransport.Consumer() into a test-owned cache of RPC instances and exposes Enumerate, Take (removing one RPC and returning it with RespChan), Drop, and Clear, plus a requeue operation that puts the RPC back on the channel so delivery to the node resumes only on a test action.
- Optionally extend MakeClusterOpts/cluster so each node's transport is pre-wired through the capture cache, giving tests a stable handle per node without racing the main loop.

### 目标已有入口

- `InmemTransport.Consumer`
- `RPC.Respond`
- `inmemPipeline.Consumer`

### 当前限制

- Analysis covers the in-boundary InmemTransport path; NetworkTransport/TCP behavior is out of boundary and not evaluated.
- InmemTransport.SetHeartbeatHandler is a no-op (inmem_transport.go:74), so heartbeats flow through the consumer channel and are capturable there; other transports may fast-path heartbeats outside this channel.

## 消息注入

- 修改前分析状态：`PATCHABLE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：The separated form (take from the consumer channel plus Respond / peer-send) is directly usable and proven by package tests, but injection is not a complete public interface: there is no combined single-call operation binding a cached message to its target, requeue of captured requests is not exposed (receive-only channel externally), and cache-state effects are implicit rather than declared.

### Analyzer 发现的实现路径（修改前）

- inbound_rpc: normal input boundary is trans.Consumer() -> rpcCh -> processRPC. Separated injection: Take from the capture cache, then rpc.Respond (responses, preserving RespChan routing) or requeue/deliver the request to the same channel (in-package write; external via a peer transport's AppendEntries/RequestVote/InstallSnapshot which reconstructs the RPC and routes to the same consumerCh). Cache effects: success - taken RPC removed, sender completes; synchronous failure - Respond(err) returns error to sender; unconfirmed async - sender times out (send/command timeout, inmem_transport.go:183-198). No combined single-call facade exists.
- append_pipeline: same capture point; a test Respond on the intercepted RPC feeds inmemPipeline.decodeResponses, which copies the response into the appendFuture and publishes it to doneCh; the pipeline future's completion mechanism (AppendFuture) is preserved.

### Analyzer 建议（修改前）

- Extend the same capture-cache wrapper with an inject method that requeues a taken RPC onto the node's consumer channel (preserving Command/Reader/RespChan) or responds on behalf of the node, so take-plus-input is a documented single operation on the same cache instance.
- Document cache effects (success, synchronous failure, unconfirmed async timeout) on the wrapper's Take and inject operations.

### 目标已有入口

- `RPC.Respond`
- `InmemTransport.AppendEntries`
- `InmemTransport.RequestVote`
- `InmemTransport.RequestPreVote`
- `InmemTransport.InstallSnapshot`
- `InmemTransport.TimeoutNow`
- `inmemPipeline.AppendEntries`

### 当前限制

- Injection analysis is scoped to InmemTransport inside the boundary; TCP/network transport behavior is out of boundary.
- A test that drops a captured request must account for the sender's 500ms default InmemTransport timeout (NewInmemTransport, inmem_transport.go:68-70).

## 时间控制

- 修改前分析状态：`INVASIVE`
- 修改前测试接口是否完整：否
- 修改前测试支持判断：No Tick or injectable Clock exists; all timers are created and consumed inside the main loops from wall clock, so tests cannot deterministically advance protocol-observed time without intrusive restructuring.

### Analyzer 发现的实现路径（修改前）

- wall_clock_timers: all protocol timing (heartbeat/election timeouts, leader lease, commit staggering, snapshot interval, replication backoff) derives from time.After/time.Now with no injectable seam; no accepted v0.1 form (explicit Tick or injectable Clock) exists.

### Analyzer 建议（修改前）

- Introduce an injectable clock abstraction (e.g., a now()/after() indirection on Config, defaulting to the real clock) and route randomTimeout and all time.After/time.Now call sites through it; tests then supply a manual clock.
- Alternatively expose an explicit Tick-style hook, which requires the same restructuring of the follower/candidate/leader select loops.

### 可参考的源码位置

- `util.go:34`：time.After(minVal + extra) - wall-clock timer creation for every randomized timeout.
- `raft.go:163`：heartbeatTimer := randomTimeout(...) consumed in the follower select loop - wall-clock election gating.
- `raft.go:677`：lease := time.After(r.config().LeaderLeaseTimeout) - wall-clock leader lease.
- `replication.go:213`：time.After(backoff(...)) and time.Now() (line 230) - wall-clock retry backoff and RPC timing.
- `saturation.go:47`：nowFn: time.Now - wall-clock metrics reporting.

### 当前限制

- Deterministic time advancement is currently achievable only by composing real-time waits with short configured timeouts (the in-package harness uses 50ms timeouts, testing.go:26-28); this does not manufacture protocol outcomes deterministically.
- Out-of-boundary: fuzzy and raft-compat subdirectories (not analyzed) contain their own time handling.

## 随机性控制

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The random choice is reachable through the standard global rand source that the target uses; a test seeds it directly (no target change) and configures the range minimum, reproducing the same choices for the same seed and call sequence.

### Analyzer 发现的实现路径（修改前）

- global_rand_election_timeout: randomTimeout consumes the process-global math/rand; tests fix it with math/rand.Seed(seed) and set Config timeouts; scope is shared across all nodes in the process (documented), domain [minVal, 2*minVal) preserved. Other randomization (NewInmemAddr UUIDs via crypto/rand, generateUUID) is address-only and not protocol-relevant.

### 目标已有入口

- `math/rand.Seed (via randomTimeout)`
- `Config.ElectionTimeout`
- `Config.HeartbeatTimeout`
- `Config.CommitTimeout`
- `Config.SnapshotInterval`

### 当前限制

- Control scope is process-global/shared across all nodes; per-node or per-instance randomness control is not available without target changes (a config-injected rand source would be a low-intrusion future option).
- Reproducibility depends on the rand call sequence; other packages in the process consuming math/rand can perturb it.
- crypto/rand-based UUIDs for in-memory addresses (NewInmemAddr/generateUUID) are not controllable, but they do not affect protocol decisions.

## 生命周期控制

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Shutdown plus NewRaft with the same caller-owned stores is a directly usable stop/restart composition, and Connect/Disconnect provides pause/resume-like availability control; the in-package harness (cluster.Close, Partition, FullyConnect) demonstrates both.

### Analyzer 发现的实现路径（修改前）

- shutdown_restart: Raft.Shutdown() (unavailable: state=Shutdown, all goroutines exited) then NewRaft(conf, fsm, logs, stable, snaps, trans) with the same caller-owned stores (available again; new instance with restored persisted state).
- availability_partition: InmemTransport Disconnect/DisconnectAll (node isolated, still running) and Connect (node rejoins); cluster harness Partition/Disconnect/FullyConnect compose the same operations.

### 目标已有入口

- `Raft.Shutdown`
- `NewRaft`
- `InmemTransport.Connect`
- `InmemTransport.Disconnect`
- `InmemTransport.DisconnectAll`
- `cluster.Partition`
- `cluster.FullyConnect`

### 当前限制

- Honest semantics: restart constructs a new Raft instance; Shutdown is not a pause and no crash/persistence/recovery behavior beyond the caller-provided stores is claimed.
- Out-of-boundary: process supervision, crash injection, and durable store implementations are not part of the module.

## 状态观察

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The existing status API and observer mechanism directly expose the minimum target-native node/global state needed by later tests (role, term, commit/applied index, configuration, log range via the test-owned store) with snapshot-safe copies; no accessor additions are needed.

### Analyzer 发现的实现路径（修改前）

- node_status: State(), LeaderWithID()/Leader(), CurrentTerm(), LastIndex(), CommitIndex(), AppliedIndex(), LastContact(), Stats(), ReloadableConfig() - all return values/copies, safe to call from any goroutine.
- configuration: GetConfiguration() -> ConfigurationFuture (Configuration() + Index()); latestConfiguration is stored as a Clone (raft.go:2217-2221).
- events: RegisterObserver(NewObserver(ch, blocking, filter)) - Observation{Raft: instance, Data: by-value copy of RaftState, LeaderObservation, PeerObservation, RequestVoteRequest, FailedHeartbeat/ResumedHeartbeatObservation}; observe() sends value copies (raft.go:1605 observe(*req)).
- storage_observation: test-owned InmemStore (LogStore/StableStore), SnapshotStore - FirstIndex/LastIndex/GetLog copy entries; snapshot List/Open for metadata.

### 目标已有入口

- `Raft.State`
- `Raft.Stats`
- `Raft.LeaderWithID`
- `Raft.CurrentTerm`
- `Raft.LastIndex`
- `Raft.CommitIndex`
- `Raft.AppliedIndex`
- `Raft.LastContact`
- `Raft.GetConfiguration`
- `Raft.ReloadableConfig`
- `Raft.LeaderCh`
- `Raft.RegisterObserver`
- `NewObserver`
- `InmemStore.GetLog`

### 当前限制

- Observation covers the pinned library state; application FSM internals and external stores are outside the boundary (FSM state is reachable only through the test's own FSM implementation).
- last_contact in Stats uses wall-clock time (api.go:1215), so its exact value is not deterministic under time control.

## 外部输入

- 修改前分析状态：`SUPPORTED`
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The existing public API plus the in-package cluster harness (MakeCluster returning []*Raft) lets a test consumer drive proposals and membership changes directly and wait on the returned futures; no target change is needed.

### Analyzer 发现的实现路径（修改前）

- proposal_apply: Raft.Apply/ApplyLog -> applyCh -> leader append/commit -> FSM.Apply; completed through the returned ApplyFuture (Error/Index/Response).
- membership_change: Raft.AddVoter/AddNonvoter/RemoveServer/DemoteVoter (and AddPeer/RemovePeer) -> configurationChangeCh -> configuration log entry -> commitment; completed through returned IndexFuture.

### 目标已有入口

- `Raft.Apply`
- `Raft.ApplyLog`
- `Raft.Barrier`
- `Raft.VerifyLeader`
- `Raft.AddVoter`
- `Raft.AddNonvoter`
- `Raft.RemoveServer`
- `Raft.DemoteVoter`
- `Raft.AddPeer`
- `Raft.RemovePeer`
- `Raft.Snapshot`
- `Raft.Restore`
- `Raft.LeadershipTransfer`
- `Raft.LeadershipTransferToServer`
- `Raft.BootstrapCluster`

### 当前限制

- Out-of-boundary: TCP/network transports, external durable stores, and application FSM semantics are not analyzed here; workload entrypoints are those of the pinned library only.
