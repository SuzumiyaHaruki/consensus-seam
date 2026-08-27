"""Fixed failure routing; orchestration is not delegated to another Agent."""

from __future__ import annotations

from .models import FailureCode, FailureRoute, ReviewOverall


def route_failure(code: FailureCode) -> FailureRoute:
    if code is FailureCode.MESSAGE_BYPASS_SUSPECTED:
        return FailureRoute.AGENT1
    if code in {
        FailureCode.BUILD_FAILED,
        FailureCode.MESSAGE_CAPTURE_FAILED,
        FailureCode.MESSAGE_SUPPRESSION_FAILED,
        FailureCode.MESSAGE_INJECTION_FAILED,
        FailureCode.TIME_CONTROL_FAILED,
        FailureCode.RANDOMNESS_CONTROL_FAILED,
        FailureCode.LIFECYCLE_CONTROL_FAILED,
        FailureCode.OBSERVATION_FAILED,
    }:
        return FailureRoute.AGENT2
    if code is FailureCode.REGRESSION_FAILED:
        # Agent 3 has already performed static review before verification. Feed the
        # concrete regression back to Agent 2 for a revised patch.
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
