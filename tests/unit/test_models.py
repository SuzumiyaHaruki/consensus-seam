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


def test_message_interface_requires_id_scope() -> None:
    with pytest.raises(ValidationError, match="message_id_scope"):
        InterfaceReport.model_validate(
            {"message_capture": {"implemented": True}}
        )


def test_reviewer_pass_requires_all_named_checks() -> None:
    payload = review_report()
    payload["checks"] = payload["checks"][:-1]
    with pytest.raises(ValidationError, match="missing checks"):
        ReviewReport.model_validate(payload)


def test_reviewer_cannot_skip_exact_target_check_for_injection() -> None:
    interface = InterfaceReport.model_validate(
        {
            "message_injection": {
                "implemented": True,
                "message_id_scope": "test_session",
                "controller_operations": "serialized",
            }
        }
    )
    payload = review_report()
    for check in payload["checks"]:
        if check["name"] == "exact_target_preserved":
            check["result"] = "NOT_APPLICABLE"
            check["evidence"] = []
    report = ReviewReport.model_validate(payload)
    with pytest.raises(ValueError, match="applicable checks PASS"):
        report.validate_for_interface(interface)


def test_reviewer_must_pass_testing_contract_conformance() -> None:
    interface = InterfaceReport.model_validate(
        {
            "message_injection": {
                "implemented": True,
                "message_id_scope": "test_session",
                "controller_operations": "serialized",
            }
        }
    )
    payload = review_report()
    for check in payload["checks"]:
        if check["name"] == "testing_contract_conformance":
            check["result"] = "NOT_APPLICABLE"
            check["evidence"] = []
    report = ReviewReport.model_validate(payload)
    with pytest.raises(ValueError, match="testing_contract_conformance"):
        report.validate_for_interface(interface)


def test_reviewer_discards_unlocated_supplementary_evidence() -> None:
    payload = review_report()
    payload["checks"][0]["evidence"].append(
        {
            "file": None,
            "symbol": None,
            "reason": "repository-wide conclusion belongs in the check reason",
        }
    )
    report = ReviewReport.model_validate(payload)
    assert len(report.checks[0].evidence) == 1


def test_reviewer_pass_still_requires_one_located_evidence_item() -> None:
    payload = review_report()
    payload["checks"][0]["evidence"] = [
        {
            "file": None,
            "symbol": None,
            "reason": "not concrete code evidence",
        }
    ]
    with pytest.raises(ValidationError, match="PASS review check requires evidence"):
        ReviewReport.model_validate(payload)
