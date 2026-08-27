from __future__ import annotations

import pytest
from pydantic import ValidationError

from consensus_seam.models import (
    CapabilityReport,
    InterfaceReport,
    ReviewReport,
)
from tests.helpers import capability_report, evidence, review_report


def test_capability_report_accepts_all_v01_capabilities() -> None:
    report = CapabilityReport.model_validate(capability_report())
    assert report.patchable() == {"message_injection"}


def test_capability_report_rejects_missing_capability() -> None:
    payload = capability_report()
    del payload["capabilities"]["observation"]
    with pytest.raises(ValidationError, match="missing: observation"):
        CapabilityReport.model_validate(payload)


def test_supported_finding_requires_code_evidence() -> None:
    payload = capability_report()
    payload["capabilities"]["message_capture"]["evidence"] = []
    with pytest.raises(ValidationError, match="requires code evidence"):
        CapabilityReport.model_validate(payload)


def test_external_input_cannot_be_patchable() -> None:
    payload = capability_report(patchable="external_input")
    with pytest.raises(ValidationError, match="discovery-only"):
        CapabilityReport.model_validate(payload)


def test_interface_report_rejects_ambiguous_failed_implementation() -> None:
    with pytest.raises(ValidationError, match="needs rediscovered_status"):
        InterfaceReport.model_validate({"message_capture": {"implemented": False}})


def test_review_pass_cannot_hide_issues() -> None:
    payload = review_report()
    payload["issues"] = [{"reason": "outbound bypass remains"}]
    with pytest.raises(ValidationError, match="PASS review cannot contain issues"):
        ReviewReport.model_validate(payload)


def test_lifecycle_supported_conflicting_with_missing_semantics_is_rejected() -> None:
    payload = capability_report()
    payload["capabilities"]["lifecycle_control"]["status"] = "SUPPORTED"
    payload["capabilities"]["lifecycle_control"]["evidence"] = evidence("Node.Pause")
    with pytest.raises(ValidationError, match="requires every obligation SATISFIED"):
        CapabilityReport.model_validate(payload)


def test_external_input_supported_requires_protocol_ingress_exclusion() -> None:
    payload = capability_report()
    payload["capabilities"]["external_input"]["obligations"][
        "protocol_ingress_excluded"
    ]["status"] = "MISSING"
    payload["capabilities"]["external_input"]["obligations"][
        "protocol_ingress_excluded"
    ]["evidence"] = []
    with pytest.raises(ValidationError, match="requires every obligation SATISFIED"):
        CapabilityReport.model_validate(payload)


def test_message_interface_requires_id_scope_and_serialized_operations() -> None:
    with pytest.raises(ValidationError, match="message_id_scope"):
        InterfaceReport.model_validate(
            {"message_capture": {"implemented": True}}
        )


def test_reviewer_pass_requires_all_named_checks() -> None:
    payload = review_report()
    payload["checks"] = payload["checks"][:-1]
    with pytest.raises(ValidationError, match="missing checks"):
        ReviewReport.model_validate(payload)
