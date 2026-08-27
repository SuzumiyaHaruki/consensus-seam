from pathlib import Path

import pytest

from consensus_seam.cli import _read_api_key_file, build_parser


def test_api_key_can_be_read_from_single_line_text_file(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key.txt"
    key_file.write_text("test-key\n", encoding="utf-8")
    assert _read_api_key_file(key_file) == "test-key"


def test_api_key_file_rejects_multiple_lines(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key.txt"
    key_file.write_text("first\nsecond\n", encoding="utf-8")
    with pytest.raises(ValueError, match="恰好包含一行"):
        _read_api_key_file(key_file)


def test_repair_cli_requires_source_run_and_checks() -> None:
    args = build_parser().parse_args(
        [
            "repair",
            "--project",
            "project.yaml",
            "--run",
            "runs/source",
            "--checks",
            "post-hoc-checks.yaml",
        ]
    )
    assert args.command == "repair"
    assert args.source_run == Path("runs/source")
    assert args.checks == Path("post-hoc-checks.yaml")
