"""Command-line entrypoint for the three v0.1 workflows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .config import load_project
from .llm.client import FakeLLMClient, UnconfiguredLLMClient
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        project = load_project(args.project)
        client = (
            FakeLLMClient.from_json_file(args.responses)
            if args.responses is not None
            else UnconfiguredLLMClient()
        )
        workflow = ConsensusWorkflow(client, runs_root=args.runs_root.resolve())
        result = getattr(workflow, args.command)(project)
        print(result.model_dump_json(indent=2))
        return 0 if result.outcome.value not in {"FAILED", "PARTIAL"} else 1
    except Exception as exc:  # CLI boundary: return a concise machine-readable error.
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
