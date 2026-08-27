"""Project-specific deterministic capability check descriptor."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import FailureCode


@dataclass(frozen=True)
class CapabilityCheck:
    """运行期确定性能力检查描述；只含命令/路由，不含测试源码。"""

    name: str
    capability: str
    command: str
    failure_code: FailureCode
