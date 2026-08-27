from consensus_seam.models import FailureCode, FailureRoute, ReviewOverall
from consensus_seam.routing import route_failure, route_review


def test_failure_routes_are_fixed() -> None:
    assert route_failure(FailureCode.MESSAGE_BYPASS_SUSPECTED) is FailureRoute.AGENT1
    assert route_failure(FailureCode.BUILD_FAILED) is FailureRoute.AGENT2
    assert route_failure(FailureCode.SEMANTIC_AMBIGUITY) is FailureRoute.NEEDS_HUMAN


def test_review_routes_are_fixed() -> None:
    assert route_review(ReviewOverall.PASS) is FailureRoute.NONE
    assert route_review(ReviewOverall.REVISE_AGENT1) is FailureRoute.AGENT1
