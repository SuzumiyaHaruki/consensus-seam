from consensus_seam.llm.profiles import resolve_model_profile
from consensus_seam.models import LLMConfig


def test_model_profiles_support_controlled_ablations() -> None:
    configured = LLMConfig()
    mixed = resolve_model_profile(configured, "mixed")
    assert mixed.analyzer.model == "deepseek-v4-flash"
    assert mixed.transformer.model == "deepseek-v4-flash"
    assert mixed.reviewer.model == "deepseek-v4-pro"

    all_pro = resolve_model_profile(configured, "all-pro")
    assert {all_pro.analyzer.model, all_pro.transformer.model, all_pro.reviewer.model} == {
        "deepseek-v4-pro"
    }
