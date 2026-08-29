from consensus_seam.models import FailureCode, FailureRoute
from consensus_seam.routing import route_failure


def test_failure_routes_are_fixed() -> None:
    assert route_failure(FailureCode.MESSAGE_CAPTURE_FAILED) is FailureRoute.AGENT2
    assert route_failure(FailureCode.BUILD_FAILED) is FailureRoute.AGENT2
    assert route_failure(FailureCode.SEMANTIC_AMBIGUITY) is FailureRoute.NEEDS_HUMAN
