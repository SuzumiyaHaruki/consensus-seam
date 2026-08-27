"""在源码和 wheel 安装中定位内置 Prompt 与规范。"""

from __future__ import annotations

from pathlib import Path


def resource_root() -> Path:
    """定位 prompts/spec 所在根目录。

    editable/source 安装时资源位于仓库根；wheel 安装时由 hatch 强制包含到
    package 目录。此函数屏蔽两种布局差异。
    """

    package_directory = Path(__file__).resolve().parent
    source_root = package_directory.parent
    if (source_root / "prompts").is_dir() and (source_root / "spec").is_dir():
        return source_root
    return package_directory
