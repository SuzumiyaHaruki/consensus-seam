# 运行 ConsensusSeam 所需材料

## 普通目标的最小输入

一次运行只要求：

1. 本地目标 Git 仓库及确定的提交版本；
2. 构建命令；
3. 原测试命令；
4. `system_boundary`，说明哪些代码层属于本次目标；
5. 目标使用的协议简介；
6. 允许 Agent 2 修改的能力范围（可选）。

不要求为每个目标预先提供人工 ground truth，也不要求人工写出完整接口答案。

`scope_roots` 和 `evidence_roots` 都是面向大型或多子系统仓库的可选配置：

- 不配置时，`scope_roots` 默认为仓库根目录，`evidence_roots` 默认为空；
- `scope_roots` 只限制 Agent 可分析和修改的文件夹；
- `evidence_roots` 只补充分析类型、构造关系和所有权所需的只读文件夹；
- 两者都是源码权限边界，不代替 `system_boundary`，也不会扩大能力范围。

普通的独立协议库无需填写这两个字段。只有仓库较大、包含多个独立子系统，或
理解核心代码确实需要查看范围外依赖时，才建议按文件夹配置；不要求人工指定到
具体文件。

## DeepSeek 运行材料

1. 可用的 DeepSeek API 密钥；
2. 访问 `https://api.deepseek.com` 或兼容网关的网络；
3. 将必要源码片段和工具结果发送给模型的授权；
4. 与目标仓库匹配的本地工具链。

推荐把纯密钥单独放在仓库外的文本文件中：

```bash
chmod 600 /绝对路径/deepseek-key.txt
```

然后运行：

```bash
consensus-seam analyze \
  --project /绝对路径/project.yaml \
  --api-key-file /绝对路径/deepseek-key.txt
```

不要把密钥写进 `project.yaml` 或提交到 Git。

## 非 Raft 目标

需要在 `spec/protocols/<protocol>.yaml` 增加一份简短协议简介，包括：

- 角色；
- 消息家族；
- 时间和随机性来源；
- 持久化概念；
- 常见观察字段；
- 已知外部输入类型。

协议简介只描述概念，不能预设目标函数名或目标实现架构。

## 完整 `run` 的项目专属材料

如果需要执行完整 `run`，目标 evaluation 可以提供：

- 每项新增能力的基础使用检查命令；
- 可选的隐藏 fixture；
- 可选的人工 ground truth；
- 本目标额外关注的严格检查。

这些材料属于具体目标，不会自动进入全局能力规范。

## etcd/raft 首轮修改实验

人工只需把独立 `go.etcd.io/raft/v3` 协议库放在系统边界内，不需要指定 `Node`、`RawNode` 或同步/异步路径。Analyzer 应自行发现这些路径并分别说明。真实网络、完整 etcd server 和跨进程存储仍由系统边界排除。

目标分支要求 Go 1.26，因此进入 build、patch 或 run 前必须准备兼容工具链，并先在未修改目标上通过：

```bash
go test ./...
```

## 可选实验输入

- 单次运行的 API 或 token 预算；
- `all-flash`、`all-pro`、`mixed` 等模型对比配置；
- 第二个不同结构的 Go 共识实现；
- 只用于事后评分的人工能力标签和评分规则。
