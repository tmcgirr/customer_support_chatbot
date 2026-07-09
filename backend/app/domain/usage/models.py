"""LLM usage rollup (contracts §7) — count-only, no PII.

A daily rollup keyed by (date, provider, model, category), so the admin Usage panel can show
token spend per provider/model/category. Written by the worker's classify/embed paths via the
adapter's ``on_usage`` hook. Chat + testing usage is derived from conversation message usage
(already persisted per assistant message), so it is NOT duplicated here.
"""

from typing import Literal

# Categories recorded from worker LLM calls. `chat` and `testing` are derived from
# conversations (by entry_page), not recorded here — listed for the response typing.
UsageCategory = Literal["chat", "testing", "summary", "insights", "labeling", "embeddings"]
