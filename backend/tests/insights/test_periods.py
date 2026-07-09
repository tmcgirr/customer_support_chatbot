"""Calendar-period math — pure, UTC. current = in-progress (manual refresh target),
last_complete = the just-elapsed period (scheduled target)."""

from datetime import UTC, datetime

from app.domain.insights.periods import current_period, last_complete_period


def test_daily_current_and_last() -> None:
    now = datetime(2026, 7, 9, 14, 30, tzinfo=UTC)  # Thursday afternoon
    cur = current_period("daily", now)
    assert cur.report_id == "daily:2026-07-09"
    assert cur.start == datetime(2026, 7, 9, tzinfo=UTC)
    assert cur.end == datetime(2026, 7, 10, tzinfo=UTC)

    last = last_complete_period("daily", now)
    assert last.report_id == "daily:2026-07-08"
    assert last.start == datetime(2026, 7, 8, tzinfo=UTC)
    assert last.end == datetime(2026, 7, 9, tzinfo=UTC)


def test_weekly_windows_align_to_iso_monday() -> None:
    now = datetime(2026, 7, 9, 14, 0, tzinfo=UTC)  # Thu; ISO week starts Mon 2026-07-06
    cur = current_period("weekly", now)
    assert cur.start == datetime(2026, 7, 6, tzinfo=UTC)
    assert cur.end == datetime(2026, 7, 13, tzinfo=UTC)
    assert cur.key.startswith("2026-W")

    last = last_complete_period("weekly", now)
    assert last.start == datetime(2026, 6, 29, tzinfo=UTC)  # the prior Monday
    assert last.end == datetime(2026, 7, 6, tzinfo=UTC)


def test_monthly_and_year_rollover() -> None:
    now = datetime(2026, 7, 9, tzinfo=UTC)
    cur = current_period("monthly", now)
    assert cur.report_id == "monthly:2026-07"
    assert cur.start == datetime(2026, 7, 1, tzinfo=UTC)
    assert cur.end == datetime(2026, 8, 1, tzinfo=UTC)

    last = last_complete_period("monthly", now)
    assert last.report_id == "monthly:2026-06"

    # January rolls the year back to the prior December.
    jan = last_complete_period("monthly", datetime(2026, 1, 15, tzinfo=UTC))
    assert jan.report_id == "monthly:2025-12"
    assert jan.end == datetime(2026, 1, 1, tzinfo=UTC)
