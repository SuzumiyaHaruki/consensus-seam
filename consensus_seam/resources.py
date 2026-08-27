"""Locate bundled prompts and specifications in source and wheel installs."""

from __future__ import annotations

from pathlib import Path


def resource_root() -> Path:
    package_directory = Path(__file__).resolve().parent
    source_root = package_directory.parent
    if (source_root / "prompts").is_dir() and (source_root / "spec").is_dir():
        return source_root
    return package_directory
