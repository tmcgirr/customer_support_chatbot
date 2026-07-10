"""Pure roll-up of LLM usage into the admin cost report.

No I/O: the endpoint fetches the worker rollup rows (llm_usage) + the chat/testing aggregation
(conversation message usage) and passes them in. Cost is applied per model via the pricing
table; an unpriced model contributes $0 and is surfaced in ``unpriced_models`` so the panel can
flag it rather than silently under-report.
"""

from dataclasses import dataclass
from typing import Any

from app.domain.usage.pricing import infer_provider, pricing_table

# Sentinel for chat usage on assistant messages that never recorded a model name (legacy /
# un-attributed spend, e.g. a turn whose stream ended before the model event fired). It is not
# a real model, so it is NOT surfaced as an "unpriced model" the operator should set a price
# for — it still appears in the by-model rollup so the tokens are accounted for.
UNKNOWN_MODEL = "unknown"


@dataclass(frozen=True)
class UsageLine:
    label: str  # the provider / model / category this line rolls up
    provider: str
    input_tokens: int
    output_tokens: int
    requests: int
    cost_usd: float
    priced: bool  # False → some rows use an unpriced model, so cost is incomplete


@dataclass(frozen=True)
class UsageBreakdown:
    input_tokens: int
    output_tokens: int
    cost_usd: float
    by_provider: list[UsageLine]
    by_model: list[UsageLine]
    by_category: list[UsageLine]
    unpriced_models: list[str]


@dataclass(frozen=True)
class _Rec:
    provider: str
    model: str
    category: str
    input_tokens: int
    output_tokens: int
    requests: int
    cost_usd: float
    priced: bool


def _normalize(worker_rows: list[dict[str, Any]], chat_rows: list[dict[str, Any]]) -> list[_Rec]:
    """Merge worker rollup rows + chat/testing rows into priced records (one pricing_table
    build for the whole call)."""
    table = pricing_table()
    recs: list[_Rec] = []

    def add(provider: str, model: str, category: str, inp: int, out: int, req: int) -> None:
        price = table.get(model)
        priced = price is not None
        cost = (
            (inp * price.input_per_mtok + out * price.output_per_mtok) / 1_000_000
            if price is not None
            else 0.0
        )
        recs.append(_Rec(provider, model, category, inp, out, req, cost, priced))

    for r in worker_rows:
        model = str(r.get("model") or UNKNOWN_MODEL)
        add(
            str(r.get("provider") or infer_provider(model)),
            model,
            str(r.get("category") or "other"),
            int(r.get("input_tokens", 0)),
            int(r.get("output_tokens", 0)),
            int(r.get("requests", 0)),
        )
    for r in chat_rows:
        model = str(r.get("model") or UNKNOWN_MODEL)
        add(
            infer_provider(model),
            model,
            "testing" if r.get("eval") else "chat",
            int(r.get("input_tokens", 0)),
            int(r.get("output_tokens", 0)),
            int(r.get("requests", 0)),
        )
    return recs


def _rollup(recs: list[_Rec], key: str) -> list[UsageLine]:
    acc: dict[str, dict[str, Any]] = {}
    for rec in recs:
        label = getattr(rec, key)
        a = acc.setdefault(
            label,
            {"provider": rec.provider, "in": 0, "out": 0, "req": 0, "cost": 0.0, "priced": True},
        )
        a["in"] += rec.input_tokens
        a["out"] += rec.output_tokens
        a["req"] += rec.requests
        a["cost"] += rec.cost_usd
        if not rec.priced:
            a["priced"] = False
    lines = [
        UsageLine(
            label=label,
            provider=str(v["provider"]),
            input_tokens=int(v["in"]),
            output_tokens=int(v["out"]),
            requests=int(v["req"]),
            cost_usd=round(float(v["cost"]), 4),
            priced=bool(v["priced"]),
        )
        for label, v in acc.items()
    ]
    lines.sort(key=lambda line: line.input_tokens + line.output_tokens, reverse=True)
    return lines


def build_breakdown(
    worker_rows: list[dict[str, Any]], chat_rows: list[dict[str, Any]]
) -> UsageBreakdown:
    recs = _normalize(worker_rows, chat_rows)
    return UsageBreakdown(
        input_tokens=sum(r.input_tokens for r in recs),
        output_tokens=sum(r.output_tokens for r in recs),
        cost_usd=round(sum(r.cost_usd for r in recs), 4),
        by_provider=_rollup(recs, "provider"),
        by_model=_rollup(recs, "model"),
        by_category=_rollup(recs, "category"),
        unpriced_models=sorted(
            {r.model for r in recs if not r.priced and r.model != UNKNOWN_MODEL}
        ),
    )


def total_cost(worker_rows: list[dict[str, Any]], chat_rows: list[dict[str, Any]]) -> float:
    """Month-to-date $ (for the budget bar / alert) — the priced sum across all rows."""
    return round(sum(r.cost_usd for r in _normalize(worker_rows, chat_rows)), 4)
