import yaml

from consensus_seam.resources import resource_root


def test_source_resource_root_contains_target_independent_go_contract() -> None:
    root = resource_root()
    capabilities = (root / "spec" / "capabilities.yaml").read_text(encoding="utf-8")
    spec = yaml.safe_load(capabilities)
    analyzer = (root / "prompts" / "agent1.md").read_text(encoding="utf-8")
    transformer = (root / "prompts" / "agent2.md").read_text(encoding="utf-8")
    reviewer = (root / "prompts" / "agent3.md").read_text(encoding="utf-8")
    contract = capabilities + analyzer + transformer + reviewer

    assert "path_pairing" in spec["capabilities"]["message_capture"]["testing_contract"]

    for required in (
        "NewMessageController",
        "Inject(handle MessageHandle) error",
        "ErrMessageNotPending",
        "NewTimeController",
        "NewRandomController",
        "NewLifecycleController",
        "ErrLifecycleUnsupported",
        "smallest focused Go tests",
        "message_cache_injection_coherence",
        "core_semantics_required",
    ):
        assert required in contract

    assert spec["prerequisites"]["target_language"]["supported"] == ["go"]
    assert "separated_take_and_input" not in contract
    assert "fixed api name" not in contract.lower()
    for target_specific_term in ("RawNode", "InteractionEnv", "Ready.Messages"):
        assert target_specific_term not in contract
