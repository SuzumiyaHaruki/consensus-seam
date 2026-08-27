"""Fixed failure routing; orchestration is not delegated to another Agent."""

from __future__ import annotations

from .models import (
    CAPABILITY_FAILURE_CODES,
    FailureCode,
    FailureRoute,
    ReviewOverall,
)


def route_failure(code: FailureCode) -> FailureRoute:
    """把确定性失败固定路由给负责修正的角色。

    实现、构建和回归问题归 Agent 2；baseline/语义歧义需要人工判断。
    路由由普通代码控制，Agent 不能自行选择下一处理者。
    """

    if code in CAPABILITY_FAILURE_CODES | {
        FailureCode.BUILD_FAILED,
        FailureCode.REGRESSION_FAILED,
    }:
        # Build, regression, and capability failures all require a revised patch.
        return FailureRoute.AGENT2
    if code in {FailureCode.BASELINE_FAILED, FailureCode.SEMANTIC_AMBIGUITY}:
        return FailureRoute.NEEDS_HUMAN
    return FailureRoute.NEEDS_HUMAN


def route_review(overall: ReviewOverall) -> FailureRoute:
    """把 Reviewer 的 overall 映射成工作流状态机分支。"""

    return {
        ReviewOverall.PASS: FailureRoute.NONE,
        ReviewOverall.REVISE_AGENT1: FailureRoute.AGENT1,
        ReviewOverall.REVISE_AGENT2: FailureRoute.AGENT2,
        ReviewOverall.NEEDS_HUMAN: FailureRoute.NEEDS_HUMAN,
    }[overall]
