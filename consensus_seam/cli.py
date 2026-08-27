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


def _read_api_key_file(path: Path) -> str:
    try:
        value = path.expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"cannot read DeepSeek API key file {path}: {exc}") from exc
    if not value:
        raise ValueError(f"DeepSeek API key file is empty: {path}")
    if len(value.splitlines()) != 1:
        raise ValueError("DeepSeek API key file must contain exactly one non-empty line")
    return value


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
        subparser.add_argument(
            "--api-key-file",
            type=Path,
            help="UTF-8 text file containing only the DeepSeek API key",
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        project = load_project(args.project)
        api_key: str | None = None
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
        result = getattr(workflow, args.command)(project)
        print(result.model_dump_json(indent=2))
        return 0 if result.outcome.value not in {"FAILED", "PARTIAL"} else 1
    except Exception as exc:  # CLI boundary: return a concise machine-readable error.
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
