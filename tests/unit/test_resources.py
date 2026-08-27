from consensus_seam.resources import resource_root


def test_source_resource_root_contains_prompts_and_specs() -> None:
    root = resource_root()
    assert (root / "prompts" / "agent1.md").is_file()
    assert (root / "spec" / "capabilities.yaml").is_file()
    capabilities = (root / "spec" / "capabilities.yaml").read_text(encoding="utf-8")
    assert "creates an active test-mode controller" in capabilities
    assert "must not require an additional public Register" in capabilities
