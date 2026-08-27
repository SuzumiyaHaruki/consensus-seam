"""Fixed failure routing; orchestration is not delegated to another Agent."""

from __future__ import annotations

from .models import (
    CAPABILITY_FAILURE_CODES,
    FailureCode,
    FailureRoute,
    ReviewOverall,
)


def route_failure(code: FailureCode) -> FailureRoute:
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
    return {
        ReviewOverall.PASS: FailureRoute.NONE,
        ReviewOverall.REVISE_AGENT1: FailureRoute.AGENT1,
        ReviewOverall.REVISE_AGENT2: FailureRoute.AGENT2,
        ReviewOverall.NEEDS_HUMAN: FailureRoute.NEEDS_HUMAN,
    }[overall]
