"""Conversation-insights document models (V1.5).

An ``InsightsReport`` is a dated snapshot (like ``daily_aggregates``) of what visitors
asked in a look-back window: clusters of near-identical questions, whether we cover each,
a proposed unified answer for the common uncovered ones, and an LLM insights narrative.

Counts + text only — no message content beyond the verbatim questions the report is about,
and never a provider id (invariant #6). Produced entirely off the worker (invariant #2).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Whether we already answer a cluster's question: served by a canonical answer / in the KB
# (covered), addressed but ambiguously (unclear), or not at all (missing).
Coverage = Literal["covered", "unclear", "missing"]

# The time horizon a report covers. Reports OVERLAP across horizons by design (a Tuesday
# conversation is in Tuesday's daily, that week's weekly, that month's monthly) — the
# per-conversation extraction/label is still computed once; a report is only a view.
PeriodType = Literal["daily", "weekly", "monthly"]


class ProposedAnswer(BaseModel):
    """A unified Q/A the engine proposes for a common, uncovered cluster. It becomes a
    canonical DRAFT (``canonical_draft_intent``) that a human must Approve before it serves —
    the engine never publishes (reuses the draft→approved gate)."""

    question: str
    answer: str
    canonical_draft_intent: str | None = None  # the draft created for the approval queue, if any


class QuestionCluster(BaseModel):
    label: str  # short human name for the theme (LLM-named)
    representative_question: str  # the canonical phrasing of the cluster
    sample_questions: list[str]  # a few verbatim member questions
    size: int  # number of conversations in the cluster
    dominant_topic: str | None = None  # the most common analytics topic label among members
    coverage: Coverage
    conversation_ids: list[str]  # members (local cnv_ ids only)
    proposed: ProposedAnswer | None = None  # set for common uncovered/unclear clusters


class InsightsReport(BaseModel):
    # populate_by_name lets us construct with id= while Mongo stores _id (the date key).
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")  # "<period_type>:<period_key>" — one per period, idempotent
    period_type: PeriodType
    period_key: str  # daily "2026-07-08" · weekly "2026-W28" · monthly "2026-07"
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    conversations_analyzed: int  # the (capped) slice actually clustered
    conversations_in_period: int = 0  # true total in the window (> analyzed ⇒ truncated)
    clusters: list[QuestionCluster]
    summary: str  # LLM narrative: demand signals, gaps, roadmap hints
