from consensus_seam.resources import resource_root


def test_source_resource_root_contains_prompts_and_specs() -> None:
    root = resource_root()
    assert (root / "prompts" / "agent1.md").is_file()
    assert (root / "spec" / "capabilities.yaml").is_file()
    capabilities = (root / "spec" / "capabilities.yaml").read_text(encoding="utf-8")
    assert "universal wrapper type are not assumed" in capabilities
    assert "materially distinct execution paths" in capabilities
    assert "target may have zero, one, or many such paths" in capabilities
    assert "could build its own slice or map" in capabilities
    assert "same authoritative cache used by" in capabilities
    assert "Selection and reference are separate" in capabilities
    assert "bare mutable-list position is not a stable reference" in capabilities
    assert "caller-supplied target object matches" in capabilities
    assert "lifecycle facade or convenience command is not required" in capabilities
    assert "NewMessageController(Transport)" not in capabilities
    analyzer_prompt = (root / "prompts" / "agent1.md").read_text(encoding="utf-8")
    transformer_prompt = (root / "prompts" / "agent2.md").read_text(encoding="utf-8")
    reviewer_prompt = (root / "prompts" / "agent3.md").read_text(encoding="utf-8")
    generic_agent_contract = capabilities + analyzer_prompt + transformer_prompt + reviewer_prompt
    for target_specific_term in ("RawNode", "InteractionEnv", "Ready.Messages"):
        assert target_specific_term not in generic_agent_contract
    assert "execution_paths" in analyzer_prompt
    assert "top-level `evidence` array" in analyzer_prompt
    assert "existing_test_interface_complete" in analyzer_prompt
    assert "structured report in English" in analyzer_prompt
    assert "structured interface report in English" in transformer_prompt
    assert "covered_paths" in transformer_prompt
    assert "uncovered_paths" in transformer_prompt
    assert "mutable aliases" in transformer_prompt
    assert "A numeric message ID is optional" in transformer_prompt
    assert "message-selection or scheduling policy" in transformer_prompt
    assert "separate take-and-input facade" in transformer_prompt
    assert "one coherent message-control seam" in transformer_prompt
    assert "an unambiguous cache-instance reference is required" in transformer_prompt
    assert "Do not document target binding as solely the caller's responsibility" in transformer_prompt
    assert "usage_examples" in transformer_prompt
    assert "no universal" in capabilities
    assert "ID form is required" in capabilities
    assert "residual, non-blocking limitations" in reviewer_prompt
    assert "silent best-effort send is not confirmed success" in reviewer_prompt
    assert "A standalone protocol-ingress API does not establish this relationship" in reviewer_prompt
    assert "message_cache_injection_coherence" in reviewer_prompt
    assert "reject bulk matching as proof of exact duplicate-instance control" in reviewer_prompt
