"""Alert evaluation (the pure function the worker logs + the /monitoring endpoint
surface). Thresholds: dead-letter / delivery-failed / privacy-failed fire critical on
any > 0; queue backlog warns strictly above its threshold."""

from app.domain.monitoring.alerts import evaluate_alerts


def _ev(**kw: object) -> list:
    base: dict[str, object] = {
        "job_counts": {},
        "request_counts": {},
        "privacy_counts": {},
        "queue_depth_threshold": 100,
    }
    base.update(kw)
    return evaluate_alerts(**base)  # type: ignore[arg-type]


def test_no_alerts_when_healthy() -> None:
    assert (
        _ev(
            job_counts={"done": 9, "pending": 3},
            request_counts={"delivered": 5},
            privacy_counts={"completed": 2},
        )
        == []
    )


def test_dead_letter_fires_critical() -> None:
    alerts = _ev(job_counts={"dead_letter": 2, "pending": 1})
    assert len(alerts) == 1
    a = alerts[0]
    assert a.name == "dead_letter_jobs" and a.severity == "critical" and a.count == 2


def test_delivery_and_privacy_failures_both_fire() -> None:
    alerts = _ev(request_counts={"delivery_failed": 1}, privacy_counts={"failed": 3})
    names = {a.name: a for a in alerts}
    assert set(names) == {"delivery_failed_requests", "privacy_erasures_failed"}
    assert all(a.severity == "critical" for a in alerts)
    assert names["privacy_erasures_failed"].count == 3


def test_queue_backlog_warns_strictly_above_threshold() -> None:
    assert _ev(job_counts={"pending": 100}, queue_depth_threshold=100) == []  # not >=
    alerts = _ev(job_counts={"pending": 101}, queue_depth_threshold=100)
    assert len(alerts) == 1 and alerts[0].name == "job_queue_backlog"
    assert alerts[0].severity == "warning" and alerts[0].threshold == 100


def test_multiple_alerts_stack() -> None:
    alerts = _ev(
        job_counts={"dead_letter": 1, "pending": 500},
        request_counts={"delivery_failed": 2},
        privacy_counts={"failed": 1},
        queue_depth_threshold=100,
    )
    assert {a.name for a in alerts} == {
        "dead_letter_jobs",
        "delivery_failed_requests",
        "privacy_erasures_failed",
        "job_queue_backlog",
    }


def test_budget_alert_fires_at_or_over_budget() -> None:
    alerts = _ev(llm_spend_usd=120.0, llm_budget_usd=100.0)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.name == "llm_budget_exceeded" and a.severity == "warning"
    assert a.count == 120 and a.threshold == 100


def test_budget_alert_silent_below_budget_or_when_disabled() -> None:
    assert _ev(llm_spend_usd=50.0, llm_budget_usd=100.0) == []  # under budget
    assert _ev(llm_spend_usd=999.0, llm_budget_usd=0.0) == []  # budget disabled (0)
