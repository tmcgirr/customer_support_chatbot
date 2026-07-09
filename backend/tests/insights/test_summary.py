"""The deterministic fallback summary used when the LLM summary is skipped/failed."""

from app.domain.insights.models import QuestionCluster
from app.domain.insights.service import _fallback_summary


def _cluster(label: str, size: int, coverage: str) -> QuestionCluster:
    return QuestionCluster(
        label=label,
        representative_question=f"{label}?",
        sample_questions=[f"{label}?"],
        size=size,
        coverage=coverage,  # type: ignore[arg-type]
        conversation_ids=["cnv_1"],
    )


def test_fallback_summary_counts_and_ranks() -> None:
    clusters = [
        _cluster("Enterprise pricing", 14, "missing"),
        _cluster("Data residency", 9, "unclear"),
        _cluster("AI Maturity Index", 7, "covered"),
    ]
    summary = _fallback_summary(clusters)

    # Coverage tallies are stated.
    assert "3 question themes this period" in summary
    assert "1 covered, 1 unclear, 1 missing" in summary
    # Top themes are ranked by size, biggest first, with counts.
    assert (
        "Top themes: Enterprise pricing (14×), Data residency (9×), AI Maturity Index (7×)."
        in summary
    )
    # Only the uncovered themes are called out as gaps to address (covered omitted).
    assert "Uncovered themes to address: Enterprise pricing, Data residency." in summary
    assert "AI Maturity Index" not in summary.split("Uncovered themes to address:")[1]
    # Never the old apologetic placeholder.
    assert "skipped" not in summary


def test_fallback_summary_singular_and_all_covered() -> None:
    summary = _fallback_summary([_cluster("Booking a call", 5, "covered")])
    assert "1 question theme this period" in summary  # singular, no trailing "s"
    assert "1 covered, 0 unclear, 0 missing" in summary
    # No uncovered themes ⇒ no "to address" clause.
    assert "to address" not in summary
