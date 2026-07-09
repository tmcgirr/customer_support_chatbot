"""LLM pricing: provider inference, cost, and the LLM_PRICING override parser."""

from app.domain.usage.pricing import (
    DEFAULT_MODEL_PRICING,
    _parse_overrides,
    cost_usd,
    infer_provider,
)


def test_infer_provider_by_model_id() -> None:
    assert infer_provider("claude-haiku-4-5") == "anthropic"
    assert infer_provider("gpt-5.4-mini") == "openai"
    assert infer_provider("text-embedding-3-small") == "openai"
    # OpenRouter uses vendor/model ids — the slash marks it.
    assert infer_provider("anthropic/claude-haiku-4.5") == "openrouter"


def test_cost_usd_uses_the_price_table() -> None:
    # claude-haiku-4-5 is $1 / $5 per 1M tokens.
    assert cost_usd("claude-haiku-4-5", 1_000_000, 0) == 1.0
    assert cost_usd("claude-haiku-4-5", 0, 1_000_000) == 5.0
    assert cost_usd("claude-haiku-4-5", 500_000, 200_000) == 1.5


def test_cost_usd_is_none_for_unpriced_model() -> None:
    assert cost_usd("some-unknown-model", 1000, 1000) is None


def test_default_table_has_anthropic_and_embeddings() -> None:
    assert DEFAULT_MODEL_PRICING["claude-opus-4-8"].provider == "anthropic"
    assert DEFAULT_MODEL_PRICING["text-embedding-3-small"].output_per_mtok == 0.0


def test_parse_overrides_skips_malformed_entries() -> None:
    parsed = _parse_overrides("gpt-5.4-mini:0.5:3, claude-x:2:8, bad, :1:1, y:notnum:1")
    assert parsed["gpt-5.4-mini"].input_per_mtok == 0.5
    assert parsed["gpt-5.4-mini"].output_per_mtok == 3.0
    assert parsed["gpt-5.4-mini"].provider == "openai"
    assert parsed["claude-x"].provider == "anthropic"
    # "bad" (no colons), "" (empty model), and "y:notnum:1" (bad float) are all dropped.
    assert set(parsed) == {"gpt-5.4-mini", "claude-x"}
