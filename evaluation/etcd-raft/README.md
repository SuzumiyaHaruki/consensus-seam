# etcd/raft 评测说明

本目录定义独立 `go.etcd.io/raft/v3` 仓库的实验输入。当前阶段先进行只读能力分析，不提供人工 ground truth、隐藏测试、转换 allowlist 或能力检查。

## 固定目标

```text
仓库：https://github.com/etcd-io/raft.git
分支：release-3.6
提交：91180476b404beeb5326194e3fcdfa1758d4f222
模块：go.etcd.io/raft/v3
```

本地目标位置：

```text
/home/nitro/Desktop/etcd-raft
```

正式分析开始前，ConsensusSeam 和目标仓库都应处于干净 Git 版本。目标仓库不应包含 ConsensusSeam Prompt、预期分类或人工答案提示。

## 工具链

固定分支当前声明：

```text
go 1.26
toolchain go1.26.7
```

本机当前 Go 是 1.25.8。`consensus-seam analyze` 不执行 manifest 中的构建和测试命令，因此可以先做源码分析。进入 baseline、patch 或完整 run 前，必须准备兼容 Go 工具链，并在未修改目标上通过 `go test ./...`。

## v0.1 分析边界

边界内：

- 独立 raft 模块；
- `Node` 与 `RawNode` 协议状态机 API；
- `Ready` 输出、同步 `Advance` 和异步存储写入行为；
- `Storage` 接口与模块自带存储实现；
- 成员变更；
- `rafttest` 中已有的进程内测试设施。

边界外：

- 真实网络和 RPC；
- 外部磁盘、WAL 和数据库实现；
- 应用状态机；
- 进程监督与完整 etcd server。

人工不指定 etcd/raft 的内部实现路径。Analyzer 应发现并比较 `Node`、`RawNode`、同步与异步存储路径；Transformer 后续应尽可能覆盖所有低侵入可实现路径，并报告剩余限制。

## 运行命令

```bash
cd /home/nitro/Desktop/consensus-seam
. .venv/bin/activate

consensus-seam analyze \
  --project /home/nitro/Desktop/consensus-seam/evaluation/etcd-raft/project.yaml \
  --api-key-file /home/nitro/Desktop/ds.txt \
  --model-profile manifest
```

预期产物包括能力报告、中文使用报告、未解决项、模型统计、工具审计和运行配置。

本轮结论采用人工定性审查，不声称分类准确率，也不进入自动修改。
