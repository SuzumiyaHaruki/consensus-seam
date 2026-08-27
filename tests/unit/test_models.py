from __future__ import annotations

import pytest
from pydantic import ValidationError

from consensus_seam.models import (
    CapabilityReport,
    InterfaceReport,
    ReviewReport,
)
from tests.helpers import capability_report


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
    with pytest.raises(ValidationError, match="PASS review cannot contain issues"):
        ReviewReport.model_validate(
            {"overall": "PASS", "issues": [{"reason": "outbound bypass remains"}]}
        )
