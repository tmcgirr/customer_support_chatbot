"""Scoring + ranking are pure — unit-test them without the model or DB."""

from datetime import UTC, datetime

from eval.config import EvalConfig
from eval.results import CaseResult, RunResult, rank


def _run(name: str, results: list[tuple[str, bool, int]]) -> RunResult:
    cases = [CaseResult(id=cid, passed=passed, latency_ms=lat) for cid, passed, lat in results]
    return RunResult(
        config=EvalConfig(name=name, model="m", prompt_version="sys-v1"),
        generated_at=datetime.now(UTC),
        cases=cases,
    )


def test_category_from_id() -> None:
    assert CaseResult(id="prc_001", passed=True).category == "prc"
    assert CaseResult(id="sec_012", passed=False).category == "sec"
    assert CaseResult(id="plain", passed=True).category == "plain"


def test_score_and_aggregates() -> None:
    run = _run("r", [("prc_001", True, 100), ("prc_002", False, 300), ("sec_001", True, 200)])
    assert run.total == 3 and run.passed == 2
    assert run.score == 2 / 3
    assert run.avg_latency_ms == 200
    assert run.by_category() == {"prc": (1, 2), "sec": (1, 0 + 1)}


def test_empty_run_is_safe() -> None:
    run = _run("empty", [])
    assert run.total == 0 and run.score == 0.0 and run.avg_latency_ms == 0


def test_rank_by_score_then_latency() -> None:
    a = _run("a", [("prc_001", True, 500)])  # 100%, slow
    b = _run("b", [("prc_001", True, 100)])  # 100%, fast → should win the tiebreak
    c = _run("c", [("prc_001", False, 50)])  # 0%
    ranked = rank([a, c, b])
    assert [r.config.name for r in ranked] == ["b", "a", "c"]


def test_as_dict_is_json_serializable() -> None:
    import json

    run = _run("r", [("prc_001", True, 100)])
    payload = run.as_dict()
    assert payload["passed"] == 1 and payload["total"] == 1 and payload["score"] == 1.0
    assert payload["cases"][0]["id"] == "prc_001"
    json.dumps(payload)  # must not raise
