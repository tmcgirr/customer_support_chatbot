"""LLM per-model pricing + cost.

Prices are USD per 1M tokens. The provider is inferred from the model id. Anthropic rates
are authoritative (from the pricing reference); OpenAI chat rates are PLACEHOLDERS (TODO:
verify) and are meant to be corrected per-environment via the ``LLM_PRICING`` override
(``config.llm_pricing_overrides``). Embeddings are billed to OpenAI regardless of the active
chat provider — Anthropic has no embeddings API, so the Claude adapter reuses OpenAI's.
"""

from dataclasses import dataclass

from app.core.config import get_settings
from app.domain.settings.models import Provider


@dataclass(frozen=True)
class ModelPrice:
    provider: Provider
    input_per_mtok: float  # USD per 1M input tokens
    output_per_mtok: float  # USD per 1M output tokens


# $/1M tokens. Anthropic = authoritative; OpenAI chat = PLACEHOLDER — verify and correct via
# the LLM_PRICING env override before trusting OpenAI $ figures. Embeddings are input-only.
DEFAULT_MODEL_PRICING: dict[str, ModelPrice] = {
    # Anthropic (authoritative)
    "claude-haiku-4-5": ModelPrice("anthropic", 1.00, 5.00),
    "claude-sonnet-5": ModelPrice("anthropic", 3.00, 15.00),
    "claude-opus-4-8": ModelPrice("anthropic", 5.00, 25.00),
    "claude-opus-4-7": ModelPrice("anthropic", 5.00, 25.00),
    # OpenAI chat — PLACEHOLDER rates. TODO: set real values via LLM_PRICING per environment.
    "gpt-5.4-mini": ModelPrice("openai", 0.25, 2.00),
    "gpt-5.4": ModelPrice("openai", 1.25, 10.00),
    # OpenAI embeddings (input-only; output priced at 0).
    "text-embedding-3-small": ModelPrice("openai", 0.02, 0.00),
    # OpenRouter — PLACEHOLDER (its per-model rates carry a markup and vary). TODO: set real
    # values via LLM_PRICING; add rows for whichever OpenRouter models you route to.
    "anthropic/claude-haiku-4.5": ModelPrice("openrouter", 1.00, 5.00),
}


def infer_provider(model: str) -> Provider:
    """Provider from the model id — the model string is the source of truth (so a fallback
    model or an embedding model is attributed correctly, not the configured primary).
    OpenRouter uses ``vendor/model`` ids (e.g. ``anthropic/claude-haiku-4.5``), so a ``/``
    marks OpenRouter; a bare ``claude-*`` is direct Anthropic; everything else is OpenAI."""
    if "/" in model:
        return "openrouter"
    return "anthropic" if model.startswith("claude") else "openai"


def _parse_overrides(raw: str) -> dict[str, ModelPrice]:
    """Parse ``"model:in:out,model2:in:out"`` (same delimited style as session_key_ring).
    Malformed entries are skipped rather than failing the whole table."""
    out: dict[str, ModelPrice] = {}
    for entry in raw.split(","):
        parts = [p.strip() for p in entry.split(":")]
        if len(parts) != 3 or not parts[0]:
            continue
        model, in_s, out_s = parts
        try:
            out[model] = ModelPrice(infer_provider(model), float(in_s), float(out_s))
        except ValueError:
            continue
    return out


def pricing_table() -> dict[str, ModelPrice]:
    """The built-in defaults with any LLM_PRICING env overrides merged on top (override wins)."""
    return {**DEFAULT_MODEL_PRICING, **_parse_overrides(get_settings().llm_pricing_overrides)}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD cost for the given token counts, or None when the model is unpriced (so callers
    can surface it as needing a price rather than silently reporting $0)."""
    price = pricing_table().get(model)
    if price is None:
        return None
    return (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1_000_000
