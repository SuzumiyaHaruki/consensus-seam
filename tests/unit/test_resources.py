from consensus_seam.resources import resource_root


def test_source_resource_root_contains_prompts_and_specs() -> None:
    root = resource_root()
    assert (root / "prompts" / "agent1.md").is_file()
    assert (root / "spec" / "capabilities.yaml").is_file()
    capabilities = (root / "spec" / "capabilities.yaml").read_text(encoding="utf-8")
    assert "a Transport abstraction is not assumed" in capabilities
    assert "materially distinct execution paths" in capabilities
    assert "NewMessageController(Transport)" not in capabilities
    analyzer_prompt = (root / "prompts" / "agent1.md").read_text(encoding="utf-8")
    transformer_prompt = (root / "prompts" / "agent2.md").read_text(encoding="utf-8")
    assert "execution_paths" in analyzer_prompt
    assert "top-level `evidence` array" in analyzer_prompt
    assert "existing_test_interface_complete" in analyzer_prompt
    assert "structured report in English" in analyzer_prompt
    assert "structured interface report in English" in transformer_prompt
    assert "covered_paths" in transformer_prompt
    assert "uncovered_paths" in transformer_prompt
