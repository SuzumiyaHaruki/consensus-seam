"""v0.1 四种工作流的命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from .config import load_posthoc_checks, load_project
from .llm.client import FakeLLMClient, UnconfiguredLLMClient
from .llm.deepseek import DeepSeekClient
from .llm.runtime import ToolCallingAgentRuntime
from .workflow import ConsensusWorkflow


def _read_api_key_file(path: Path) -> str:
    """读取单行 API Key。

    Key 文件允许放在仓库外部；这里只返回内存中的字符串，后续不会把
    Key 写入 run-config、统计文件或工具审计。
    """

    try:
        value = path.expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"无法读取 DeepSeek API 密钥文件 {path}：{exc}") from exc
    if not value:
        raise ValueError(f"DeepSeek API 密钥文件为空：{path}")
    if len(value.splitlines()) != 1:
        raise ValueError("DeepSeek API 密钥文件必须恰好包含一行非空内容")
    return value


def build_parser() -> argparse.ArgumentParser:
    """构造四个工作流共用的命令行参数。

    analyze/patch/run/repair 的差别由 Workflow 方法决定，项目路径、模型配置和
    凭据加载方式保持一致，避免四个入口出现行为漂移。
    """

    parser = argparse.ArgumentParser(prog="consensus-seam")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, description in (
        ("analyze", "运行只读能力分析 Agent"),
        ("patch", "运行 Analyzer、Transformer 和独立 Reviewer"),
        ("run", "运行 baseline、三个 Agent 和确定性验证"),
        ("repair", "使用生成后的真实测试修复已有候选接口"),
    ):
        subparser = subparsers.add_parser(command, help=description)
        subparser.add_argument("--project", required=True, type=Path)
        subparser.add_argument(
            "--responses",
            type=Path,
            help="按调用顺序保存确定性 Agent 原始响应的 JSON 数组",
        )
        subparser.add_argument(
            "--runs-root",
            type=Path,
            default=Path(__file__).resolve().parents[1] / "runs",
        )
        subparser.add_argument(
            "--model-profile",
            choices=("manifest", "mixed", "all-flash", "all-pro"),
            default="manifest",
            help="覆盖各 Agent 模型，用于受控对比实验",
        )
        subparser.add_argument(
            "--api-key-file",
            type=Path,
            help="只包含 DeepSeek API 密钥的 UTF-8 文本文件",
        )
        if command == "repair":
            subparser.add_argument(
                "--run",
                dest="source_run",
                required=True,
                type=Path,
                help="包含原候选报告和 changes.patch 的运行目录",
            )
            subparser.add_argument(
                "--checks",
                required=True,
                type=Path,
                help="生成后 capability checks 与 fixture 映射 YAML",
            )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 边界：解析配置、选择 Runtime、执行工作流并输出 JSON。

    返回码约定：0 表示工作流正常完成；1 表示得到 FAILED/PARTIAL；2 表示
    配置、凭据、模型调用或框架内部异常。异常只输出类型和消息，不输出
    traceback，便于脚本稳定解析。
    """

    args = build_parser().parse_args(argv)
    try:
        project = load_project(args.project)
        api_key: str | None = None
        # --responses 用于可重复的单元/集成实验；真实调用才创建 DeepSeek
        # transport 和带工具循环的 Runtime。
        if args.responses is not None:
            runtime = FakeLLMClient.from_json_file(args.responses)
        else:
            key_file = args.api_key_file
            if key_file is None and not os.environ.get("DEEPSEEK_API_KEY"):
                configured_file = os.environ.get("DEEPSEEK_API_KEY_FILE")
                key_file = Path(configured_file) if configured_file else None
            api_key = (
                _read_api_key_file(key_file)
                if key_file is not None
                else os.environ.get("DEEPSEEK_API_KEY")
            )
        if args.responses is None and api_key:
            deepseek = DeepSeekClient(
                api_key,
                base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )
            runtime = ToolCallingAgentRuntime(deepseek)
        elif args.responses is None:
            runtime = UnconfiguredLLMClient()
        workflow = ConsensusWorkflow(
            runtime,
            runs_root=args.runs_root.resolve(),
            model_profile=args.model_profile,
        )
        # 子命令名称受 argparse choices 限制，因此这里的动态分派不会调用
        # 任意对象属性。
        if args.command == "repair":
            posthoc_checks = load_posthoc_checks(
                args.checks,
                repository=project.repository,
            )
            result = workflow.repair(
                project,
                source_run=args.source_run,
                checks=posthoc_checks,
            )
        else:
            result = getattr(workflow, args.command)(project)
        print(result.model_dump_json(indent=2))
        return 0 if result.outcome.value not in {"FAILED", "PARTIAL"} else 1
    except Exception as exc:  # CLI 边界只返回简短、机器可读的错误。
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
