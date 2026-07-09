"""Operational alert evaluation — the single source of truth for what counts as a
pageable condition.

A pure function over the same status counters the ``/monitoring`` endpoint exposes,
so the worker (which logs alerts for a log-based pager) and the admin endpoint (which
surfaces them for a dashboard) agree exactly. Alerts carry counts + local names only —
never PII (invariant #5)."""

from dataclasses import dataclass
from typing import Literal

AlertSeverity = Literal["critical", "warning"]


@dataclass(frozen=True)
class Alert:
    name: str
    severity: AlertSeverity
    count: int
    threshold: int
    message: str


def evaluate_alerts(
    *,
    job_counts: dict[str, int],
    request_counts: dict[str, int],
    privacy_counts: dict[str, int],
    queue_depth_threshold: int,
) -> list[Alert]:
    """Return the currently-firing alerts. `critical` conditions each mean a resource is
    stuck and needs a human (fire when > 0); `warning` conditions are degradations."""
    alerts: list[Alert] = []

    dead_letter = job_counts.get("dead_letter", 0)
    if dead_letter > 0:
        alerts.append(
            Alert(
                "dead_letter_jobs",
                "critical",
                dead_letter,
                0,
                "Jobs exhausted their retries and dead-lettered — investigate + reconcile.",
            )
        )

    delivery_failed = request_counts.get("delivery_failed", 0)
    if delivery_failed > 0:
        alerts.append(
            Alert(
                "delivery_failed_requests",
                "critical",
                delivery_failed,
                0,
                "Requests parked as delivery_failed — fix the destination, then admin-redeliver.",
            )
        )

    privacy_failed = privacy_counts.get("failed", 0)
    if privacy_failed > 0:
        alerts.append(
            Alert(
                "privacy_erasures_failed",
                "critical",
                privacy_failed,
                0,
                "Verified subject-erasures could not complete — legal-sensitive, follow up now.",
            )
        )

    queue_depth = job_counts.get("pending", 0)
    if queue_depth > queue_depth_threshold:
        alerts.append(
            Alert(
                "job_queue_backlog",
                "warning",
                queue_depth,
                queue_depth_threshold,
                "Worker queue is backing up — the worker may be down or overloaded.",
            )
        )

    return alerts
