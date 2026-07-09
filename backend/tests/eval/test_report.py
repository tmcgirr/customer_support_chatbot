"""The HTML report is a pure function of the runs — assert it contains the score, the
ranking/diff for multiple configs, and that model output is HTML-escaped."""

from datetime import UTC, datetime

from eval.config import EvalConfig
from eval.report import render_html
from eval.results import CaseResult, RunResult


def _run(name: str, cases: list[CaseResult]) -> RunResult:
    return RunResult(
        config=EvalConfig(name=name, model="gpt-x", prompt_version="sys-v1"),
        generated_at=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        cases=cases,
    )


def test_single_run_report_has_score_and_cases() -> None:
    run = _run(
        "current",
        [
            CaseResult(id="prc_001", passed=True, routed_intent="pricing", latency_ms=120),
            CaseResult(
                id="sec_001", passed=False, failures=["must_escalate but none"], latency_ms=90
            ),
        ],
    )
    html = render_html([run])
    assert "<!doctype html>" in html.lower()
    assert "50%" in html  # 1 of 2 passed
    assert "prc_001" in html and "pricing" in html
    assert "must_escalate but none" in html
    assert "Ranking" not in html  # no ranking for a single run


def test_multi_run_report_ranks_and_diffs() -> None:
    good = _run(
        "good", [CaseResult(id="prc_001", passed=True), CaseResult(id="sec_001", passed=True)]
    )
    bad = _run(
        "bad", [CaseResult(id="prc_001", passed=True), CaseResult(id="sec_001", passed=False)]
    )
    html = render_html([bad, good])  # unranked input
    assert "Ranking" in html and "Case × config" in html
    # The disagreeing case (sec_001) is highlighted as a differ row.
    assert "differ" in html
    # Best config appears before the worse one in the ranking (good = 100% beats bad = 50%).
    assert html.index("good") < html.index("bad")


def test_model_output_is_escaped() -> None:
    run = _run("x", [CaseResult(id="c1", passed=True, text="<script>alert(1)</script>")])
    html = render_html([run])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_empty_runs_render() -> None:
    assert "No runs" in render_html([])
