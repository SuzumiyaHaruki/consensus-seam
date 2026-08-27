"""在不硬编码 Agent 类的情况下解析 manifest 与 CLI 模型配置。"""

from __future__ import annotations

from typing import Literal

from ..models import AgentModelConfig, LLMConfig


ModelProfile = Literal["manifest", "mixed", "all-flash", "all-pro"]


def resolve_model_profile(config: LLMConfig, profile: ModelProfile) -> LLMConfig:
    """在保留 thinking/token 等参数的前提下覆盖三个模型名称。

    总是返回副本，避免一次 CLI 实验的 profile 原地污染 LoadedProject。
    """

    if profile == "manifest":
        return config.model_copy(deep=True)

    def configured(model: str, source: AgentModelConfig) -> AgentModelConfig:
        return source.model_copy(update={"model": model})

    if profile == "mixed":
        return LLMConfig(
            analyzer=configured("deepseek-v4-flash", config.analyzer),
            transformer=configured("deepseek-v4-flash", config.transformer),
            reviewer=configured("deepseek-v4-pro", config.reviewer),
        )
    selected = "deepseek-v4-flash" if profile == "all-flash" else "deepseek-v4-pro"
    return LLMConfig(
        analyzer=configured(selected, config.analyzer),
        transformer=configured(selected, config.transformer),
        reviewer=configured(selected, config.reviewer),
    )
