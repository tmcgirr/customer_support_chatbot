"""Knowledge-gap ranking (pure): aggregate NON-COVERED clusters across DAILY reports into a
magnitude-then-persistence ranking, ignoring covered clusters and overlapping non-daily
horizons. Deterministic — no clock, no randomness."""

from datetime import UTC, datetime

from app.domain.insights.gaps import rank_gaps
from app.domain.insights.models import InsightsReport, ProposedAnswer, QuestionCluster


def _cluster(
    *,
    topic: str | None,
    size: int,
    coverage: str = "missing",
    label: str | None = None,
    rep: str = "a question",
    proposed: bool = True,
) -> QuestionCluster:
    return QuestionCluster(
        label=label or (topic or "theme"),
        representative_question=rep,
        sample_questions=[rep],
        size=size,
        dominant_topic=topic,
        coverage=coverage,  # type: ignore[arg-type]
        conversation_ids=[f"cnv_{i}" for i in range(size)],
        proposed=(
            ProposedAnswer(question="Q?", answer="A", canonical_draft_intent="insight_x")
            if proposed
            else None
        ),
    )


def _report(
    day: int, clusters: list[QuestionCluster], *, period_type: str = "daily"
) -> InsightsReport:
    d = datetime(2026, 7, day, tzinfo=UTC)
    return InsightsReport(
        id=f"{period_type}:2026-07-{day:02d}",
        period_type=period_type,  # type: ignore[arg-type]
        period_key=f"2026-07-{day:02d}",
        generated_at=d,
        window_start=d,
        window_end=d,
        conversations_analyzed=10,
        conversations_in_period=10,
        clusters=clusters,
        summary="s",
    )


def test_empty_reports_yield_no_gaps() -> None:
    assert rank_gaps([]) == []


def test_covered_clusters_are_excluded() -> None:
    reports = [_report(8, [_cluster(topic="pricing", size=9, coverage="covered")])]
    assert rank_gaps(reports) == []


def test_aggregates_by_topic_across_days() -> None:
    reports = [
        _report(8, [_cluster(topic="pricing", size=3)]),
        _report(9, [_cluster(topic="pricing", size=4)]),
    ]
    gaps = rank_gaps(reports)
    assert len(gaps) == 1
    assert gaps[0].total_asked == 7  # 3 + 4
    assert gaps[0].days_seen == 2


def test_non_daily_horizons_are_ignored_no_double_count() -> None:
    # A weekly report overlaps the same conversations as the daily; it must not double-count.
    reports = [
        _report(8, [_cluster(topic="pricing", size=3)]),
        _report(8, [_cluster(topic="pricing", size=3)], period_type="weekly"),
    ]
    gaps = rank_gaps(reports)
    assert len(gaps) == 1 and gaps[0].total_asked == 3 and gaps[0].days_seen == 1


def test_rank_is_magnitude_then_persistence() -> None:
    # A: 10 asks over 1 day. B: 8 asks over 3 days. Magnitude wins → A first.
    reports = [
        _report(8, [_cluster(topic="a", size=10)]),
        _report(6, [_cluster(topic="b", size=3)]),
        _report(7, [_cluster(topic="b", size=3)]),
        _report(9, [_cluster(topic="b", size=2)]),
    ]
    gaps = rank_gaps(reports)
    assert [g.key for g in gaps] == ["topic:a", "topic:b"]
    assert gaps[0].total_asked == 10 and gaps[0].days_seen == 1
    assert gaps[1].total_asked == 8 and gaps[1].days_seen == 3


def test_magnitude_tie_broken_by_persistence() -> None:
    reports = [
        _report(8, [_cluster(topic="a", size=6)]),  # 6 over 1 day
        _report(6, [_cluster(topic="b", size=3)]),  # 6 over 2 days
        _report(7, [_cluster(topic="b", size=3)]),
    ]
    gaps = rank_gaps(reports)
    assert [g.key for g in gaps] == ["topic:b", "topic:a"]  # equal magnitude, b more persistent


def test_descriptive_fields_come_from_the_latest_occurrence() -> None:
    # Newest report FIRST in the list (as the repo returns them), so this pins selection by
    # generated_at — a naive "last occurrence wins" would wrongly pick the older day-6 fields.
    reports = [
        _report(9, [_cluster(topic="pricing", size=2, label="new label", rep="new q")]),
        _report(6, [_cluster(topic="pricing", size=2, label="old label", rep="old q")]),
    ]
    gap = rank_gaps(reports)[0]
    assert gap.label == "new label"
    assert gap.representative_question == "new q"
    assert gap.last_period_key == "2026-07-09"


def test_equal_magnitude_and_persistence_break_by_key() -> None:
    # Same total_asked (4) and days_seen (1) → the final tie-break is the key, ascending,
    # so the ranking is deterministic even when the first two sort keys collide.
    reports = [_report(8, [_cluster(topic="zebra", size=4), _cluster(topic="alpha", size=4)])]
    assert [g.key for g in rank_gaps(reports)] == ["topic:alpha", "topic:zebra"]


def test_two_same_topic_clusters_in_one_report_sum_but_count_one_day() -> None:
    reports = [_report(8, [_cluster(topic="pricing", size=3), _cluster(topic="pricing", size=4)])]
    gap = rank_gaps(reports)[0]
    assert gap.total_asked == 7 and gap.days_seen == 1


def test_topicless_clusters_merge_by_normalized_label() -> None:
    reports = [
        _report(8, [_cluster(topic=None, size=2, label="Refund  Policy")]),
        _report(9, [_cluster(topic=None, size=3, label="refund policy")]),
        _report(9, [_cluster(topic=None, size=1, label="Something else")]),
    ]
    gaps = {g.key: g for g in rank_gaps(reports)}
    assert gaps["label:refund policy"].total_asked == 5  # normalized-equal labels merge
    assert "label:something else" in gaps


def test_limit_truncates_to_the_top_gaps() -> None:
    reports = [_report(8, [_cluster(topic=f"t{i}", size=i) for i in range(1, 6)])]
    gaps = rank_gaps(reports, limit=2)
    assert len(gaps) == 2
    assert [g.total_asked for g in gaps] == [5, 4]  # the two biggest


def test_proposed_and_draft_intent_flow_through() -> None:
    reports = [_report(8, [_cluster(topic="pricing", size=3, proposed=True)])]
    gap = rank_gaps(reports)[0]
    assert gap.proposed_question == "Q?"
    assert gap.canonical_draft_intent == "insight_x"


def test_gap_with_no_proposal_has_none_fields() -> None:
    reports = [_report(8, [_cluster(topic="pricing", size=3, proposed=False)])]
    gap = rank_gaps(reports)[0]
    assert gap.proposed_question is None and gap.canonical_draft_intent is None
