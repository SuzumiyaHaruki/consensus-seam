# HashiCorp Raft 评测说明

本目录定义 `github.com/hashicorp/raft` 的盲分析与低侵入接口生成实验。它与
etcd/raft 同属 Go Raft，但运行机制不同，适合检查 ConsensusSeam 是否过度
依赖显式 Tick、Ready 或特定测试 harness。

## 固定目标

```text
仓库：https://github.com/hashicorp/raft.git
Tag：v1.7.3
提交：c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe
模块：github.com/hashicorp/raft
Go：go.mod 声明 1.20；本机验证使用 1.25.8
```

本地目标位置：

```text
/home/nitro/Desktop/hashicorp-raft
```

目标仓库保持 detached HEAD 和干净工作树，正式实验固定完整提交，不在运行
时追随 tag 或 `main`。

## 分析边界

边界内：

- 公开 `Raft` API 与协议状态循环；
- Transport 抽象和 `InmemTransport`；
- observer、future 与配置入口；
- 模块自带的内存 store、snapshot 和进程内测试支持。

边界外：

- `NetworkTransport`、TCP socket 和真实网络 deadline 行为；
- 外部持久化 store 实现；
- 应用 FSM 的业务语义；
- 进程监督；
- `raft-compat/`、`fuzzy/` 和 `bench/` 子目录。

系统边界只限定本次允许声称和修改的范围，不预先给出内部路径、能力分类、
目标 API 形状或修改方案。Analyzer 仍需从源码自行发现真实时间、消息、运行
循环和测试支持之间的关系。

## 已验证的目标基线

```bash
cd /home/nitro/Desktop/hashicorp-raft
git describe --tags --exact-match
git rev-parse HEAD
go test ./...
```

当前结果：tag 为 `v1.7.3`，完整提交与上文一致，原生测试全部通过。完整测试
耗时约 131 秒，因此后续运行中较长的 baseline/test 阶段属于正常现象。

## 运行盲分析与接口生成

```bash
cd /home/nitro/Desktop/consensus-seam
. .venv/bin/activate

consensus-seam patch \
  --project /home/nitro/Desktop/consensus-seam/evaluation/hashicorp-raft/project.yaml \
  --api-key-file /home/nitro/Desktop/ds.txt \
  --model-profile manifest
```

该项目清单不包含人工 ground truth、transform allowlist、capability checks 或
隐藏测试。`patch` 结束后已经得到候选代码、接口报告、使用说明和 Reviewer
结论；需要进一步验证时，再根据真实生成接口准备可选的 post-hoc checks。
