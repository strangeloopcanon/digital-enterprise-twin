from __future__ import annotations

from vei.llm import providers


def test_build_usage_uses_builtin_openai_pricing_when_env_is_absent(
    monkeypatch,
) -> None:
    monkeypatch.delenv("VEI_OPENAI_GPT_5_MINI_INPUT_USD_PER_1M", raising=False)
    monkeypatch.delenv("VEI_OPENAI_GPT_5_MINI_OUTPUT_USD_PER_1M", raising=False)
    monkeypatch.delenv("VEI_OPENAI_INPUT_USD_PER_1M", raising=False)
    monkeypatch.delenv("VEI_OPENAI_OUTPUT_USD_PER_1M", raising=False)
    monkeypatch.delenv("VEI_LLM_INPUT_USD_PER_1M", raising=False)
    monkeypatch.delenv("VEI_LLM_OUTPUT_USD_PER_1M", raising=False)

    usage = providers._build_usage(
        provider="openai",
        model="gpt-5-mini",
        prompt_tokens=20_166,
        completion_tokens=3_240,
    )

    assert usage.estimated_cost_usd == 0.0115215
