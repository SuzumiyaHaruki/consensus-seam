# etcd-raft 测试接口使用报告

本报告同时列出目标系统已有接口和本次 Agent 生成的接口。
能力状态、源码证据和完整限制以 `capability-report.json` 为准。

## 消息捕获

- 分析状态：`SUPPORTED`
- 覆盖边界：Inside: Ready processing and rafttest pending message store. Outside: real network send (application transport) is not part of the protocol library.

### Analyzer 发现的实现路径

- RawNode synchronous path: Ready() returns rd with rd.Messages; test holds rd and chooses whether to send; captured messages never auto-continue (suppression = not sending).
- Node asynchronous channel path: test consumes Ready() channel; run loop already called acceptReady (node.go:441); messages require explicit application send to continue.
- rafttest InteractionEnv path: ProcessReady moves non-local messages into env.Messages; deliver-msgs/drop controls continuation explicitly.
- Uncovered internal path: rafttest network harness (rafttest/node.go:85-91) auto-sends rd.Messages via goroutines with no capture hook; this harness is unexported (package rafttest internal test tooling only).

### 目标已有入口

- `RawNode.Ready()/Ready() channel (rawnode.go:133, node.go:552)`
- `rafttest ProcessReady (interaction_env_handler_process_ready.go:45), env.Messages pending store, DeliverMsgs (interaction_env_handler_deliver_msgs.go:81)`

### 限制

- No stable message IDs exist in env.Messages; selection is by recipient+type via splitMsgs (rafttest/interaction_env_handler_stabilize.go:117), not by ID.
- rafttest network harness auto-sends Ready messages (rafttest/node.go:85-91), so capture is only possible at the harness level, not exposed to its users.
- With AsyncStorageWrites, capture must also account for MsgStorageAppend/MsgStorageApply local-thread messages (rawnode.go:165-175), which must still be processed for progress.

## 消息注入

- 分析状态：`SUPPORTED`
- 覆盖边界：Inside: Step entrypoints on Node/RawNode and rafttest delivery. Outside: real network transport.

### Analyzer 发现的实现路径

- RawNode path: test selects a captured message and calls rn.Step(m); synchronous; target object is the held *RawNode; content and From/To preserved.
- Node path: test calls node.Step(ctx, m); enqueued on recvc and processed by the run goroutine (node.go:399-404); asynchronous; response-message filter drops messages from unknown peers (node.go:400-403).
- rafttest path: DeliverMsgs matches pending messages by recipient and type, removes them (consumes only the selected messages), and steps synchronously into the RawNode; drop option suppresses instead.

### 目标已有入口

- `RawNode.Step(m) (rawnode.go:118) — synchronous`
- `Node.Step(ctx, m) (node.go:478) — asynchronous via recvc`
- `rafttest DeliverMsgs / SendSnapshot (interaction_env_handler_deliver_msgs.go:81, interaction_env_handler_send_snapshot.go:34)`

### 限制

- env.Messages has no stable message IDs; injection is by recipient+type ordering (splitMsgs preserves order, stabilize.go:117-127).
- Node.Step is asynchronous (returns once queued); injection effects are observed only after the run loop processes the message.
- Local proposal messages (MsgProp) on the Node path have From rewritten to the local ID (node.go:393); captured peer-to-peer network messages are not mutated.
- RawNode.Step rejects local messages from non-local targets (ErrStepLocalMsg) and responses from unknown peers (ErrStepPeerNotFound, rawnode.go:120-125); previously captured legal messages pass.

## 时间控制

- 分析状态：`SUPPORTED`
- 覆盖边界：Inside: tick-driven protocol clock on Node/RawNode and rafttest. Outside: wall-clock sources used by test harnesses to invoke Tick.

### Analyzer 发现的实现路径

- RawNode synchronous path: test calls rn.Tick() n times; deterministic election/heartbeat progression.
- Node asynchronous path: test calls n.Tick(); run loop consumes tickc and calls rn.Tick() (node.go:438-439); buffered channel (128) tolerates bursts.
- rafttest path: tick-election/tick-heartbeat advance ElectionTick/HeartbeatTick ticks at once.
- Harness limitation: rafttest network harness drives Node.Tick from a wall-clock time.NewTicker (rafttest/node.go:67-73); this is test tooling, not protocol time.

### 目标已有入口

- `RawNode.Tick / TickQuiesced (rawnode.go:64, 78)`
- `Node.Tick (node.go:463)`
- `rafttest Tick / tick-election / tick-heartbeat (rafttest/interaction_env_handler_tick.go:23-38)`

### 限制

- No injectable Clock abstraction exists (search found none); explicit Tick is the supported form and is sufficient.
- state_trace.go:337 sleeps 1ms in trace emission for cross-node alignment; this is tracing output pacing, not protocol time.
- rafttest/network.go:88-89 and rafttest/node.go:82-88 use time.Sleep for simulated network/storage latency in the unexported harness.
- Wall-clock time in tests (e.g., rafttest/network_test.go:63, node_test.go:366) is measurement tooling, not protocol state.

## 随机性控制

- 分析状态：`PATCHABLE`
- 覆盖边界：Inside: raft state machine randomization and rafttest command. Outside: nothing relevant.

### Analyzer 发现的实现路径

- In-module white-box path: raft package tests directly write randomizedElectionTimeout (raft_test.go:4092) — works.
- rafttest path: set-randomized-election-timeout command calls the plumbed setter — works only when the setter is supplied from the raft package test binary (interaction_test.go:32).
- Uncovered: external black-box path — no public API to fix or seed randomness; globalRand (crypto/rand) is not injectable.

### 目标已有入口

- `White-box: setRandomizedElectionTimeout / SetRandomizedElectionTimeout (raft_test.go:4092-4100)`
- `rafttest: set-randomized-election-timeout command (rafttest/interaction_env_handler_set_randomized_election_timeout.go:24)`

### 限制

- SetRandomizedElectionTimeout lives in raft_test.go and is compiled only into the raft package test binary; rafttest external consumers cannot supply it themselves (field type requires access to unexported raft state).
- The randomized timeout is reset whenever the node resets its term/state (raft.go:784-793), so the fixed value is ephemeral across elections.
- No other protocol randomness exists in the library (verified: no rand usage outside raft.go:97 and test code).

## 生命周期控制

- 分析状态：`SUPPORTED`
- 覆盖边界：Inside: module-provided Node/RawNode construction, Stop, Storage interface, MemoryStorage, rafttest node add/restart helpers. Outside: real WAL/disk durability and process supervision.

### Analyzer 发现的实现路径

- Fresh creation: StartNode/NewRawNode+Bootstrap appends initial conf-change entries.
- Recovery path: RestartNode/NewRawNode load HardState+ConfState+log from app Storage (newRaft, raft.go:437-485); Config.Applied restores applied index.
- Stop path: Node.Stop cooperatively stops the run loop; RawNode is thread-unsafe and has no lifecycle to stop.
- Crash-recovery: the module's boundary is Storage; durable WAL/disk handling is the application's responsibility (outside boundary).

### 目标已有入口

- `StartNode (node.go:276), RestartNode (node.go:286), NewRawNode (rawnode.go:51), RawNode.Bootstrap (bootstrap.go:30)`
- `Node.Stop (node.go:336); RawNode has no Stop (no goroutine to stop)`
- `Config.Applied (raft.go:145), Config.Storage (raft.go:144)`
- `rafttest AddNodes / rafttest node restart (rafttest/interaction_env_handler_add_nodes.go, rafttest/node.go)`

### 限制

- Restart/crash-recovery semantics depend on the application-supplied Storage; the module does not decide what survives a crash (MemoryStorage is explicitly in-memory).
- Stop discards all volatile state; there is no pause/resume at the Node API level (rafttest network harness has unexported pause/resume helpers, rafttest/node.go:148-157).

## 状态观察

- 分析状态：`SUPPORTED`
- 覆盖边界：Inside: module status APIs and rafttest commands. Outside: application-level state-machine state.

### Analyzer 发现的实现路径

- RawNode synchronous path: Status()/BasicStatus()/WithProgress() read raft state directly.
- Node asynchronous path: Status() round-trips through the status channel to the run goroutine (node.go:452-453).
- rafttest path: raft-state/status/raft-log commands print node views from Status() and raftLog.

### 目标已有入口

- `RawNode.Status / BasicStatus / WithProgress (rawnode.go:498-531)`
- `Node.Status (node.go:574)`
- `rafttest raft-state / status / raft-log commands`

### 限制

- Fields remain protocol-specific (no universal state schema), which is acceptable per v0.1.
- Progress map is only populated on the leader (status.go:71-73).

## 外部输入

- 分析状态：`SUPPORTED`
- 覆盖边界：Inside: go.etcd.io/raft/v3 module (Node, RawNode, rafttest). Outside: real networking, WAL/disk, application state machines.

### Analyzer 发现的实现路径

- RawNode synchronous path: NewRawNode then Propose/ProposeConfChange/ReadIndex drive raft.Step directly; Ready()/Advance() consumed by the test.
- Node asynchronous path: StartNode/RestartNode spawn run loop; Propose/ProposeConfChange/ReadIndex queued via propc/recvc channels and processed by the run goroutine.
- rafttest InteractionEnv path: propose / propose-conf-change commands call env.Nodes[idx].Propose(...) on RawNode instances.
- Control entrypoints (Campaign, TransferLeadership, ForgetLeader) are protocol-control inputs, not application workload; they are reported separately from Step-based peer ingress.

### 目标已有入口

- `Node.Propose / Node.ProposeConfChange / Node.ReadIndex / Node.Campaign / Node.TransferLeadership / Node.ForgetLeader (node.go)`
- `RawNode.Propose / RawNode.ProposeConfChange / RawNode.ReadIndex / RawNode.Campaign / RawNode.TransferLeader / RawNode.ForgetLeader (rawnode.go)`
- `rafttest propose / propose-conf-change commands (rafttest)`

### 限制

- Peer-to-peer protocol ingress via Step (node.go:478, rawnode.go:118) is excluded from external-input accounting; MsgHup/MsgBeat/MsgCheckQuorum generated by Tick (raft.go:849-889) are internal events, not external inputs.
