"""Knowledge-gap ranking — a read-side VIEW over stored insights reports (no model calls,
no new storage). Aggregates the NON-COVERED question clusters across recent DAILY reports so
the biggest, most-persistent gaps — the questions visitors keep asking that we don't answer
well — rank first. It only re-reads and re-sorts data the insights pipeline already produced.

Daily only: reports OVERLAP across horizons (a Tuesday conversation is in Tuesday's daily,
that week's weekly, that month's monthly), so mixing horizons would double-count. Daily is the
finest non-overlapping base — and the only horizon that auto-drafts proposals.

Pure and deterministic (no clock, no randomness): the same reports always yield the same
ranking, which keeps the admin view stable and the unit tests simple.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.insights.models import Coverage, InsightsReport, QuestionCluster


@dataclass
class KnowledgeGap:
    """One aggregated, ranked gap. Descriptive fields come from the most RECENT occurrence
    (the current assessment); the aggregates span every occurrence in the window."""

    key: str  # stable merge key: the dominant analytics topic, else the normalized label
    label: str  # human theme name (most recent occurrence)
    representative_question: str  # most recent occurrence — the API edge MASKS this for admin
    coverage: Coverage  # most recent occurrence's coverage (missing / unclear)
    total_asked: int  # Σ cluster.size across occurrences — magnitude
    days_seen: int  # distinct daily reports it appeared in as a gap — persistence
    proposed_question: str | None
    proposed_answer: str | None
    canonical_draft_intent: str | None  # the approve-link intent, if a draft was created
    last_period_key: str  # the daily key of the most recent occurrence (e.g. "2026-07-08")
    last_generated_at: datetime


@dataclass
class _Acc:
    """Mutable accumulator for one merge key while folding across reports."""

    key: str
    total_asked: int = 0
    report_ids: set[str] = field(default_factory=set)
    latest: QuestionCluster | None = None
    latest_at: datetime | None = None
    latest_period_key: str = ""


def _merge_key(cluster: QuestionCluster) -> str:
    """The cross-day identity of a gap. The analytics ``dominant_topic`` is stable across
    days (a fixed label taxonomy) so it's the primary key; when a cluster has no topic, fall
    back to the normalized (nondeterministic) LLM label — imperfect but keeps singletons apart."""
    topic = (cluster.dominant_topic or "").strip().lower()
    if topic:
        return f"topic:{topic}"
    return "label:" + " ".join(cluster.label.lower().split())


def rank_gaps(reports: list[InsightsReport], *, limit: int = 20) -> list[KnowledgeGap]:
    """Fold the NON-COVERED clusters of the DAILY reports into ranked gaps, biggest first.

    ``reports`` may contain any horizon; non-daily reports are ignored here so overlapping
    weekly/monthly snapshots can never double-count the same conversations. Ranking is by
    magnitude (total questions asked), then persistence (distinct days), then key (stable)."""
    acc: dict[str, _Acc] = {}
    for report in reports:
        if report.period_type != "daily":
            continue  # daily only — other horizons overlap and would double-count
        for cluster in report.clusters:
            if cluster.coverage == "covered":
                continue  # a gap is only what we DON'T answer well (missing / unclear)
            key = _merge_key(cluster)
            entry = acc.get(key)
            if entry is None:
                entry = _Acc(key=key)
                acc[key] = entry
            entry.total_asked += cluster.size
            entry.report_ids.add(report.id)  # daily id is unique per day → distinct-day count
            # Keep the most RECENT occurrence's descriptive fields (the current assessment of
            # the theme). Same-day ties keep the first (largest, since clusters are size-sorted).
            if entry.latest_at is None or report.generated_at > entry.latest_at:
                entry.latest = cluster
                entry.latest_at = report.generated_at
                entry.latest_period_key = report.period_key

    gaps: list[KnowledgeGap] = []
    for entry in acc.values():
        latest = entry.latest
        if latest is None or entry.latest_at is None:
            continue  # unreachable (set together), but keeps both non-None for the type checker
        proposed = latest.proposed
        gaps.append(
            KnowledgeGap(
                key=entry.key,
                label=latest.label,
                representative_question=latest.representative_question,
                coverage=latest.coverage,
                total_asked=entry.total_asked,
                days_seen=len(entry.report_ids),
                proposed_question=proposed.question if proposed else None,
                proposed_answer=proposed.answer if proposed else None,
                canonical_draft_intent=proposed.canonical_draft_intent if proposed else None,
                last_period_key=entry.latest_period_key,
                last_generated_at=entry.latest_at,
            )
        )
    gaps.sort(key=lambda g: (-g.total_asked, -g.days_seen, g.key))
    return gaps[:limit]
