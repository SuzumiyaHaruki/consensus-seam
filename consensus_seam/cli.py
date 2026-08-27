"""Command-line entrypoint for the three v0.1 workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from .config import load_project
from .llm.client import FakeLLMClient, UnconfiguredLLMClient
from .llm.deepseek import DeepSeekClient
from .llm.runtime import ToolCallingAgentRuntime
from .workflow import ConsensusWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="consensus-seam")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, description in (
        ("analyze", "run the read-only Capability Analyzer"),
        ("patch", "run Analyzer, Transformer, and independent Reviewer"),
        ("run", "run baseline, all Agents, and deterministic verification"),
    ):
        subparser = subparsers.add_parser(command, help=description)
        subparser.add_argument("--project", required=True, type=Path)
        subparser.add_argument(
            "--responses",
            type=Path,
            help="JSON array of deterministic raw Agent responses",
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
            help="override per-Agent models for controlled experiments",
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        project = load_project(args.project)
        if args.responses is not None:
            runtime = FakeLLMClient.from_json_file(args.responses)
        elif api_key := os.environ.get("DEEPSEEK_API_KEY"):
            deepseek = DeepSeekClient(
                api_key,
                base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )
            runtime = ToolCallingAgentRuntime(deepseek)
        else:
            runtime = UnconfiguredLLMClient()
        workflow = ConsensusWorkflow(
            runtime,
            runs_root=args.runs_root.resolve(),
            model_profile=args.model_profile,
        )
        result = getattr(workflow, args.command)(project)
        print(result.model_dump_json(indent=2))
        return 0 if result.outcome.value not in {"FAILED", "PARTIAL"} else 1
    except Exception as exc:  # CLI boundary: return a concise machine-readable error.
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
