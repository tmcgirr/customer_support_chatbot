"""Calendar-period math for insights reports (pure, UTC, testable).

A report covers a CALENDAR period — a day, an ISO week, or a calendar month — so reports
are stable and comparable (yesterday's daily never changes once the day is over). Each
period has a stable ``key`` used as part of the report's ``_id`` (``daily:2026-07-08``),
so the scheduled run and a manual run for the same period write the SAME report — idempotent
overwrite, never a duplicate.
"""

from datetime import UTC, datetime, timedelta

from app.domain.insights.models import PeriodType


class Period:
    """A concrete reporting window: its type, stable key, and [start, end) bounds (UTC)."""

    __slots__ = ("type", "key", "start", "end")

    def __init__(self, type_: PeriodType, key: str, start: datetime, end: datetime) -> None:
        self.type = type_
        self.key = key
        self.start = start
        self.end = end

    @property
    def report_id(self) -> str:
        return f"{self.type}:{self.key}"


def _day_start(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(dt: datetime) -> datetime:
    return _day_start(dt).replace(day=1)


def _next_month_start(month_start: datetime) -> datetime:
    # month_start is the 1st at 00:00; advance to the 1st of the next month.
    if month_start.month == 12:
        return month_start.replace(year=month_start.year + 1, month=1)
    return month_start.replace(month=month_start.month + 1)


def current_period(period_type: PeriodType, now: datetime) -> Period:
    """The in-progress period containing ``now`` (a manual run refreshes this)."""
    now = now.astimezone(UTC)
    if period_type == "daily":
        start = _day_start(now)
        return Period("daily", start.strftime("%Y-%m-%d"), start, start + timedelta(days=1))
    if period_type == "weekly":
        start = _day_start(now) - timedelta(days=now.weekday())  # back to Monday
        iso = start.isocalendar()
        return Period("weekly", f"{iso.year}-W{iso.week:02d}", start, start + timedelta(days=7))
    start = _month_start(now)
    return Period("monthly", start.strftime("%Y-%m"), start, _next_month_start(start))


def last_complete_period(period_type: PeriodType, now: datetime) -> Period:
    """The most recent period that has fully ELAPSED (the scheduled run targets this —
    e.g. just after UTC midnight it produces yesterday's daily report)."""
    current = current_period(period_type, now)
    # One step before the current window: use a timestamp inside the prior period.
    return current_period(period_type, current.start - timedelta(seconds=1))
