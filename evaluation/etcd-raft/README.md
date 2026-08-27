# etcd/raft 评测说明

本目录定义独立 `go.etcd.io/raft/v3` 仓库的实验输入。实验主流程进行盲分析和低侵入接口生成，不提供人工 ground truth、预设 API 形状、隐藏测试、转换 allowlist 或能力检查。该主流程会直接产出接口代码，不依赖后续修复。

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

本机当前 Go 是 1.25.8。运行时使用 `GOTOOLCHAIN=auto`，让 Go 根据目标模块声明获取兼容工具链。正式生成前，应先在未修改目标上通过 `go test ./...`。

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

## 完整主流程：接口生成

先验证目标原仓库：

```bash
cd /home/nitro/Desktop/etcd-raft
GOTOOLCHAIN=auto go test ./...
```

然后运行盲分析、接口生成和独立 Reviewer：

```bash
cd /home/nitro/Desktop/consensus-seam
. .venv/bin/activate

GOTOOLCHAIN=auto consensus-seam patch \
  --project /home/nitro/Desktop/consensus-seam/evaluation/etcd-raft/project.yaml \
  --api-key-file /home/nitro/Desktop/ds.txt \
  --model-profile manifest
```

预期产物包括能力报告、接口报告、中文结构的使用报告、候选补丁、Reviewer 报告、未解决项、模型统计、工具审计和运行配置。目标原仓库不会被直接修改。

## 可选流程：生成后测试与修复

如果希望进一步验证或提高候选质量，可以根据主流程实际生成的 `interface-report.json` 和 `USAGE.md` 编写后置测试，再运行：

```bash
cd /home/nitro/Desktop/consensus-seam
. .venv/bin/activate

GOTOOLCHAIN=auto consensus-seam repair \
  --project /home/nitro/Desktop/consensus-seam/evaluation/etcd-raft/project.yaml \
  --run /home/nitro/Desktop/consensus-seam/runs/<主流程时间戳目录> \
  --checks /绝对路径/etcd-post-hoc-checks.yaml \
  --api-key-file /home/nitro/Desktop/ds.txt \
  --model-profile manifest
```

后置测试第一次通过时结果为 `PASS`；需要 Agent 2 修复后通过时结果为 `REPAIRED`。两者都只证明实际测试场景，不声称完备协议正确性。
