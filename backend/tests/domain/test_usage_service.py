"""Usage roll-up service: merge worker rollup + chat/testing rows, apply pricing."""

from app.domain.usage.service import build_breakdown, total_cost

# One worker rollup row (summary, 1M input on haiku = $1) + two chat/testing rows.
WORKER = [
    {
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "category": "summary",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "requests": 2,
    }
]
CHAT = [
    {
        "model": "claude-haiku-4-5",
        "eval": False,
        "input_tokens": 0,
        "output_tokens": 1_000_000,
        "requests": 1,
    },
    {
        "model": "gpt-5.4-mini",
        "eval": True,
        "input_tokens": 1000,
        "output_tokens": 0,
        "requests": 1,
    },
]


def test_build_breakdown_merges_worker_and_chat_rows() -> None:
    b = build_breakdown(WORKER, CHAT)
    assert b.input_tokens == 1_000_000 + 1000
    assert b.output_tokens == 1_000_000
    # Categories: summary (worker), chat + testing (from entry_page split).
    assert {line.label for line in b.by_category} == {"summary", "chat", "testing"}
    # summary(1M in = $1) + chat(1M out = $5) on haiku, plus the tiny gpt testing cost.
    haiku = next(line for line in b.by_model if line.label == "claude-haiku-4-5")
    assert haiku.cost_usd == 6.0
    assert {line.label for line in b.by_provider} == {"anthropic", "openai"}


def test_unpriced_model_is_flagged_not_hidden() -> None:
    b = build_breakdown(
        [
            {
                "provider": "openai",
                "model": "mystery-model",
                "category": "labeling",
                "input_tokens": 100,
                "output_tokens": 50,
                "requests": 1,
            }
        ],
        [],
    )
    assert b.unpriced_models == ["mystery-model"]
    line = next(line for line in b.by_model if line.label == "mystery-model")
    assert line.priced is False and line.cost_usd == 0.0
    # Tokens are still counted even when unpriced.
    assert line.input_tokens == 100 and line.output_tokens == 50


def test_unknown_model_counted_but_not_flagged_as_unpriced() -> None:
    # Chat usage on an assistant message that never recorded a model → "unknown" sentinel.
    # It's not a real model, so it must NOT appear in the "set LLM_PRICING" notice, but its
    # tokens are still accounted for in the by-model rollup.
    b = build_breakdown(
        [],
        [{"model": None, "eval": False, "input_tokens": 500, "output_tokens": 200, "requests": 3}],
    )
    assert b.unpriced_models == []
    line = next(line for line in b.by_model if line.label == "unknown")
    assert line.priced is False and line.cost_usd == 0.0
    assert line.input_tokens == 500 and line.output_tokens == 200


def test_total_cost_sums_priced_rows() -> None:
    assert total_cost(WORKER, []) == 1.0
    assert total_cost([], []) == 0.0
