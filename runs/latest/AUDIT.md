# etcd-raft 测试接口审计报告

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
Analyzer 内容描述修改前状态；生成接口和 Reviewer 内容描述候选修改后状态。
机器可读细节以`capability-report.json`、`interface-report.json`、`review-report.json`为准。

## 消息捕获

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Inside: RawNode.Ready/Advance, node.run Ready channel, rafttest ProcessReady/env.Messages/AppendWork/ApplyWork, async storage message queues. Outside: real network transport (application sends messages itself) and disk.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The rafttest env is an exported package: external consumers can call ProcessReady, inspect env.Messages (order preserved by splitMsgs, full message content), select instances by Recipient/type or by direct slice manipulation, and remove/clear via DeliverMsgs. Node-mode Ready/Advance gives the same control through the public interface. Ready fields are documented read-only and acceptReady detaches internal slices (rawnode.go:433); env.Messages stores messages by value. No second store is needed: env.Messages is the single authoritative cache for network-bound messages, with AppendWork/ApplyWork as the authoritative per-node storage-thread queues consumed by their own processors.

### Analyzer 发现的实现路径（修改前）

- RawNode/rafttest synchronous path: Ready() returns the Ready; ProcessReady handles storage and routes outbound messages into env.Messages (rafttest/interaction_env_handler_process_ready.go:60-76); messages remain cached until the test calls DeliverMsgs; no automatic continuation.
- AsyncStorageWrites path: Ready.Messages carries MsgStorageAppend/MsgStorageApply; ProcessReady routes them into Node.AppendWork/ApplyWork (interaction_env_handler_process_ready.go:66-69); ProcessAppendThread/ProcessApplyThread later surface their Responses into env.Messages (process_append_thread.go:77, process_apply_thread.go:67).
- Node channel path: node.run arms readyc only when the application is ready to receive (node.go:358-370, 440-447); the application holds rd.Messages; continuation requires the application to act and call Advance (node.go:448-451; rawnode.go:482).
- rafttest network harness path (same-package only): harness goroutine sends rd.Messages into raftNetwork.recvQueues channels (rafttest/node.go:85-91, network.go:70-109); capture at the in-process queue.

### 目标已有入口

- `RawNode.Ready (rawnode.go:133), RawNode.HasReady (rawnode.go:453), RawNode.Advance (rawnode.go:482)`
- `Node.Ready() <-chan Ready (node.go:552), Node.Advance (node.go:554)`
- `rafttest InteractionEnv.ProcessReady (rafttest/interaction_env_handler_process_ready.go:45), env.Messages field (rafttest/interaction_env.go:52), Node.AppendWork/ApplyWork fields (rafttest/interaction_env.go:42-43)`
- `rafttest InteractionEnv.ProcessAppendThread (rafttest/interaction_env_handler_process_append_thread.go:47), ProcessApplyThread (rafttest/interaction_env_handler_process_apply_thread.go:46)`

### 当前限制

- Real network send is outside the boundary; in Node mode the application must perform the actual send of rd.Messages itself.
- The rafttest network harness (rafttest/node.go) auto-sends messages into in-process queues; that harness is unexported and usable only by same-package tests.
- Crash simulation at the Ready boundary is not implemented (TODO in ProcessReady).
- In Node mode, Ready must be handled before Advance (documented contract); holding multiple unhandled Readys is not permitted.

## 消息注入

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Inside: RawNode.Step, Node.Step, rafttest DeliverMsgs and node resolution in env.Nodes. Outside: real network receive path and transport framing.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The rafttest env provides a synchronous take-and-deliver wrapper (DeliverMsgs) with explicit cache effect (handled messages removed from env.Messages, drops printed) and real target-object binding: AddNodes constructs actual RawNode objects with consecutive IDs (rafttest/interaction_env_handler_add_nodes.go:94-100) and DeliverMsgs resolves msg.To to env.Nodes[To-1]. For Node/RawNode consumers, the captured message value can be stepped directly through the public Step API. Delivery is synchronous, so a delivered message is not silently dropped; Step errors are surfaced in the env output buffer and the handled count is returned.

### Analyzer 发现的实现路径（修改前）

- rafttest env path: DeliverMsgs splits env.Messages by recipient (msg.To) and type, removes handled messages, then synchronously steps each into env.Nodes[To-1].Step (rafttest/interaction_env_handler_deliver_msgs.go:81-103); drops are explicit and reported.
- Node channel path: Node.Step(ctx, msg) sends the unchanged message to recvc; node.run calls r.Step synchronously in the node goroutine (node.go:399-404, 478-485).
- RawNode direct path: RawNode.Step(msg) synchronously calls r.raft.Step after rejecting local messages from non-local From and responses from unknown peers (rawnode.go:118-127).

### 目标已有入口

- `rafttest InteractionEnv.DeliverMsgs (rafttest/interaction_env_handler_deliver_msgs.go:81)`
- `Node.Step (node.go:478)`
- `RawNode.Step (rawnode.go:118)`

### 当前限制

- DeliverMsgs assumes nodes are numbered consecutively from 1 (toIdx = msg.To - 1); delivery to a not-yet-instantiated node index would panic (drops to such nodes are allowed and documented).
- Step errors from DeliverMsgs are printed to the env output buffer rather than returned as errors; the handled count is returned.
- The rafttest network harness (rafttest/node.go) injection path (n.Step in the node goroutine) is unexported/same-package only; external consumers use public Node.Step or RawNode.Step.

## 时间控制

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Inside: Node.Tick, RawNode.Tick/TickQuiesced, raft tickElection/tickHeartbeat, rafttest Tick handlers. Outside: the application's real-time scheduler that calls Tick, and wall-clock-based test networks (rafttest/node.go uses real timers).
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Tick is directly testable: RawNode.Tick and Node.Tick are the complete deterministic time interface, and the rafttest env wraps them with Tick/tick-election/tick-heartbeat. The protocol has no wall-clock dependency (raft.go imports no time package), so no injectable Clock is needed; no ForceTimeout/ForceElection shortcut is introduced.

### Analyzer 发现的实现路径（修改前）

- RawNode path: RawNode.Tick() calls rn.raft.tick() synchronously (rawnode.go:64-66).
- Node channel path: Node.Tick() sends to the buffered tickc (capacity 128) and node.run calls n.rn.Tick() (node.go:438-439, 463-470); ticks are dropped with a warning if the node blocks too long.
- rafttest path: env.Tick(idx, num) loops RawNode.Tick (rafttest/interaction_env_handler_tick.go:34-38); tick-election/tick-heartbeat call it ElectionTick/HeartbeatTick times.

### 目标已有入口

- `Node.Tick (node.go:463)`
- `RawNode.Tick (rawnode.go:64), RawNode.TickQuiesced (rawnode.go:78, deprecated)`
- `rafttest InteractionEnv.Tick (rafttest/interaction_env_handler_tick.go:34), tick-election / tick-heartbeat handlers`
- `raft.tickElection (raft.go:850), raft.tickHeartbeat (raft.go:862)`

### 当前限制

- Node.Tick drops ticks (with a warning) when tickc is full (node.go:463-470), so tests using Node mode must keep the node responsive; RawNode mode is exact.
- TickQuiesced (rawnode.go:78) advances only electionElapsed and is deprecated; it subverts heartbeat/election processing and should not be used for time control.
- Whether an election actually fires after N ticks depends on the randomized election timeout (see randomness_control).

## 随机性控制

- 修改前分析状态：`PATCHABLE`
- 覆盖边界：Inside: randomizedElectionTimeout field, globalRand usage in raft.reset/resetRandomizedElectionTimeout, rafttest set-randomized-election-timeout handler. Outside: application-level random scheduling and network drop/delay randomness in the test network (rafttest/network.go).
- 修改前测试接口是否完整：否
- 修改前测试支持判断：The module's own test suite can fix the timeout through the test-build-only exported SetRandomizedElectionTimeout and the rafttest option hook, but external consumers cannot: there is no Config field, no injectable random source, and crypto/rand cannot be seeded. The fixed value also does not survive state changes, so even in-module repeatability is limited to one state epoch.
- 本次修改：已生成接口

### Analyzer 发现的实现路径（修改前）

- Module-internal test path: raft.SetRandomizedElectionTimeout(rn, v) fixes r.randomizedElectionTimeout; rafttest handler requires v != 0. Transient: raft.reset re-randomizes on every term/state change (raft.go:791-793).
- Production path: randomizedElectionTimeout is drawn as electionTimeout + globalRand.Intn(electionTimeout) from crypto/rand (raft.go:95-102, 2049-2051); there is no seed, configuration, or injection point available to external consumers.

### Analyzer 建议（修改前）

- Add an optional Config field (e.g., RandomizedElectionTimeout int, 0 meaning 'randomize as today') validated in Config.validate to stay within [ElectionTick, 2*ElectionTick-1] (or document that domain), and have resetRandomizedElectionTimeout honor it instead of globalRand when set.
- Alternatively, promote SetRandomizedElectionTimeout from raft_test.go into a non-test file (e.g., a package-level function taking *RawNode), keeping the rafttest option hook; low intrusion, no algorithm change.
- Keep the rafttest set-randomized-election-timeout command and InteractionOpts hook; add the domain validation there as well.

### 目标已有入口

- `raft.setRandomizedElectionTimeout / raft.SetRandomizedElectionTimeout (raft_test.go:4092-4100, test build only)`
- `rafttest InteractionOpts.SetRandomizedElectionTimeout (rafttest/interaction_env.go:31-33) and set-randomized-election-timeout handler (rafttest/interaction_env_handler_set_randomized_election_timeout.go:24)`
- `raft.reset -> resetRandomizedElectionTimeout (raft.go:793, 2049)`

### 本次生成接口

- 调用入口：`raft.go / Config.RandomizedElectionTimeout：Optional configuration field: when non-zero it fixes the randomized election timeout to this value on every state change instead of drawing a new random value from [ElectionTick, 2*ElectionTick-1]; zero (default) preserves the existing randomized behavior.`

### 使用与范围

- 生产路径：Default behavior is byte-for-byte unchanged when the field is 0: resetRandomizedElectionTimeout still draws electionTimeout + globalRand.Intn(electionTimeout). The only production changes are the new domain check in Config.validate (non-zero values must be within [ElectionTick, 2*ElectionTick-1], else newRaft panics like other Config errors) and resetRandomizedElectionTimeout honoring the override. No protocol conditions, message semantics, pastElectionTimeout, or tickElection logic changed.
- 测试路径：Set Config.RandomizedElectionTimeout before calling NewRawNode/StartNode/RestartNode; the value is fixed at node construction and re-applied on every state change. For rafttest, pass randomized-election-timeout=<n> to add-nodes. The existing test-build-only raft.SetRandomizedElectionTimeout (raft_test.go:4098) and the set-randomized-election-timeout command remain available to in-module tests but stay transient.
- Zero value preserves the existing crypto/rand-backed drawing from [ElectionTick, 2*ElectionTick-1]; the random-choice algorithm itself is not replaced, only made fixable.
- Non-zero values are validated to preserve the target's legal domain: values below ElectionTick or above 2*ElectionTick-1 (including negatives) are rejected by Config.validate with an explicit error.
- Unlike the previously only existing mechanism (test-build-only raft.SetRandomizedElectionTimeout, which is re-randomized by reset() on every state change), the Config value survives every state change because resetRandomizedElectionTimeout honors the override.
- External consumers (any package importing go.etcd.io/raft/v3) can now fix election timing through the public Config field on RawNode and Node paths; previously only the raft package's own test build could do so.
- The rafttest set-randomized-election-timeout command still requires InteractionOpts.SetRandomizedElectionTimeout (test-build-only); external rafttest users should use the add-nodes randomized-election-timeout arg instead, which persists across state changes.
- All module tests pass: go test ./... (raft, rafttest, confchange, quorum, raftpb, tracker).
- No INVASIVE_REDISCOVERED: the change is a configuration knob honored by the existing resetRandomizedElectionTimeout, with no protocol-condition or message-semantics modification.

### 已覆盖路径

- Config option path: newRaft copies Config.RandomizedElectionTimeout into raft.randomizedElectionTimeoutOverride (raft.go newRaft struct literal), and resetRandomizedElectionTimeout (raft.go:2069) honors the override on every reset(), so the fixed value survives becomeFollower/becomeCandidate/becomeLeader state changes.
- RawNode path: NewRawNode(cfg) with a fixed RandomizedElectionTimeout produces repeatable election timing (election fires on exactly the configured tick count); Config.validate rejects out-of-domain values at construction (raft.go:316-320).
- Node path: StartNode/RestartNode build the raft from the same *Config, so the fixed timeout applies identically on the channel-based Node path.
- rafttest harness path: the add-nodes command accepts randomized-election-timeout=<n> and applies it to every added node's Config (rafttest/interaction_env_handler_add_nodes.go:72-73); the existing transient set-randomized-election-timeout command and its test-build-only hook are unchanged for in-module tests.

### 实际实现方式

- add_test_configuration: new optional Config.RandomizedElectionTimeout field (0 = randomize as today), validated by Config.validate to stay within [ElectionTick, 2*ElectionTick-1]
- add_test_hook: resetRandomizedElectionTimeout honors the configured override instead of calling globalRand.Intn when the override is non-zero
- add_target_language_tests: randomness_test.go (raft package: domain validation, persistence across state changes, deterministic election timing, default range) and rafttest/interaction_env_randomness_test.go (add-nodes arg wiring and deterministic election through the env)

### 修改前已知限制（供对照）

- Network drop/delay randomness in rafttest/network.go (rand.New(rand.NewSource(1))) is harness-level, not protocol randomness.
- Without fixing the timeout, identical ticks may or may not trigger elections because randomizedElectionTimeout is in [ElectionTick, 2*ElectionTick-1] (raft.go:416-419).

## 生命周期控制

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Inside: Node.Stop, StartNode/RestartNode, Config.Storage, MemoryStorage, and the rafttest node harness (pause/resume/stop/restart). Outside: real WAL/disk durability, process supervision, and crash injection.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：Public Stop + StartNode/RestartNode directly provide unavailable-and-restore control for external consumers; the rafttest harness adds pause/resume/stop/restart for same-package tests. The v0.1 minimum (make unavailable, restore, mechanism stated honestly) is met without new target code.

### Analyzer 发现的实现路径（修改前）

- Node path: n.Stop() gracefully terminates the node goroutine (node.go:336-346); a new instance is created via StartNode or RestartNode from the same Config.Storage (node.go:276-294), i.e. reconstruction from storage.
- rafttest node harness path (same-package tests): pause() buffers inbound messages and replies them on resume() on the same instance (rafttest/node.go:101-113, 151-158); stop() disconnects and terminates, restart() builds a new node from the same MemoryStorage (rafttest/node.go:122-146).
- RawNode path: no lifecycle API; making the node unavailable is simply not calling its methods (pure test-driver control).

### 目标已有入口

- `Node.Stop (node.go:336)`
- `StartNode (node.go:276)`
- `RestartNode (node.go:286)`
- `RawNode has no stop/restart API; availability is the caller's scheduling (test driver stops calling Ready/Tick)`
- `rafttest node harness (same-package only): pause (rafttest/node.go:151), resume (rafttest/node.go:156), stop (rafttest/node.go:122), restart (rafttest/node.go:131)`

### 当前限制

- Pause/resume is available only inside the rafttest package (unexported node type, rafttest/node.go:28); external consumers must use Stop + RestartNode.
- Crash simulation is not implemented: ProcessReady contains 'TODO(tbg): Allow simulating crashes here' (rafttest/interaction_env_handler_process_ready.go:46).
- Restart fidelity depends on the application's Storage durability; MemoryStorage is volatile.
- RawNode has no lifecycle API; availability is purely the caller's scheduling.

## 状态观察

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Inside: Status/BasicStatus/WithProgress and rafttest status/raft-state/raft-log handlers. Outside: application state machine contents and persistent storage layout.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The existing Status API is directly sufficient: BasicStatus exposes ID, HardState (term/vote/commit), SoftState (role/lead), Applied, LeadTransferee; Status adds Config and leader Progress; WithProgress provides allocation-free progress inspection. getBasicStatus returns value copies and getProgressCopy clones Inflights, so no caller can mutate protocol state through the observation interface (snapshot safety). Log range is observable through the application's Storage (e.g., MemoryStorage.Entries, rafttest RaftLog handler).

### Analyzer 发现的实现路径（修改前）

- Node path: Node.Status() is served by the run goroutine via the status channel (node.go:452-453, 574-582).
- RawNode path: Status/BasicStatus/WithProgress are synchronous reads of the raft struct (rawnode.go:498-531; status.go:56-76).
- rafttest path: status, raft-state, and raft-log handlers aggregate Status and Storage for the datadriven harness (rafttest/interaction_env_handler_status.go:33, interaction_env_handler_raft_log.go:33).

### 目标已有入口

- `Node.Status (node.go:574)`
- `RawNode.Status (rawnode.go:498), RawNode.BasicStatus (rawnode.go:505), RawNode.WithProgress (rawnode.go:521)`
- `rafttest InteractionEnv.Status (rafttest/interaction_env_handler_status.go:33), handleRaftState, RaftLog (rafttest/interaction_env_handler_raft_log.go:33)`

### 当前限制

- Status.Progress is populated only on the leader (status.go:71-73).
- Log range is not part of Status; it is observed via the Storage interface (MemoryStorage.Entries / rafttest raft-log).
- SoftState.Lead must be accessed with atomic operations on the Node path (documented in node.go:41).

## 外部输入

- 修改前分析状态：`SUPPORTED`
- 覆盖边界：Inside: Node/RawNode public proposal, membership-change, and read-request entrypoints plus the rafttest propose/propose-conf-change handlers. Outside: application transport, real network ingress of peer messages, and wall-clock scheduling.
- 修改前测试接口是否完整：是
- 修改前测试支持判断：The entrypoints are direct public APIs on both Node and RawNode, and rafttest additionally exposes propose/propose-conf-change commands; no new target code is required for v0.1 discovery/use.

### Analyzer 发现的实现路径（修改前）

- Node channel path: Node.Propose/ProposeConfChange/ReadIndex enqueue into propc/recvc; node.run (node.go:348) steps them in its goroutine; Propose waits on a result channel via stepWithWaitOption (node.go:507-550).
- RawNode synchronous path: RawNode.Propose/ProposeConfChange/ReadIndex call r.raft.Step synchronously on the caller's goroutine (rawnode.go:90-107, 561).
- rafttest harness path: rafttest propose and propose-conf-change handlers call the RawNode methods of env.Nodes (rafttest/interaction_env_handler_propose.go:32).

### 目标已有入口

- `Node.Propose (node.go:474)`
- `Node.ProposeConfChange (node.go:495)`
- `Node.ReadIndex (node.go:613)`
- `RawNode.Propose (rawnode.go:90)`
- `RawNode.ProposeConfChange (rawnode.go:101)`
- `RawNode.ReadIndex (rawnode.go:561)`
- `rafttest InteractionEnv.Propose / propose-conf-change handlers`
- `Control-only entrypoints (not workload): Node.Campaign, Node.TransferLeadership, Node.ForgetLeader, RawNode.Campaign/TransferLeader/ForgetLeader`

### 当前限制

- Proposals may be dropped without error (documented on Node.Propose); retry policy is the application's concern.
- Campaign/TransferLeadership/ForgetLeader are local control operations, not workload input.

## 独立 Reviewer 结论

- 总体结论：`PASS`

### 非阻塞剩余风险

- For external consumers, an out-of-domain non-zero RandomizedElectionTimeout surfaces as a panic from newRaft via NewRawNode/StartNode/RestartNode rather than a returned error; this matches the existing Config validation style for all other Config errors and is documented in the interface notes.
