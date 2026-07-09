"""The PDF report renders to a valid PDF for one run and a comparison, and survives non-latin
text in a model response (fpdf2 core fonts are latin-1 only)."""

from datetime import UTC, datetime

from eval.config import EvalConfig
from eval.pdf import render_pdf
from eval.results import CaseResult, RunResult


def _run(name: str, cases: list[CaseResult]) -> RunResult:
    return RunResult(
        config=EvalConfig(name=name, model="gpt-x", prompt_version="sys-v1"),
        generated_at=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        cases=cases,
    )


def test_single_run_pdf_is_valid() -> None:
    run = _run(
        "current",
        [
            CaseResult(id="prc_001", passed=True, routed_intent="pricing", latency_ms=120),
            CaseResult(
                id="sec_001", passed=False, failures=["must_escalate but none"], latency_ms=90
            ),
        ],
    )
    data = render_pdf([run])
    assert isinstance(data, bytes) and data[:5] == b"%PDF-" and len(data) > 600


def test_comparison_pdf_is_valid() -> None:
    a = _run("baseline", [CaseResult(id="prc_001", passed=True)])
    b = _run("candidate", [CaseResult(id="prc_001", passed=False, failures=["x"])])
    data = render_pdf([a, b])
    assert data[:5] == b"%PDF-"


def test_pdf_survives_unicode_in_output() -> None:
    run = _run("x", [CaseResult(id="c1", passed=True, routed_intent="pricing—€✓", text="rün")])
    data = render_pdf([run])  # must not raise on non-latin-1 chars
    assert data[:5] == b"%PDF-"


def test_empty_pdf_is_valid() -> None:
    assert render_pdf([])[:5] == b"%PDF-"


def test_pdf_survives_a_page_length_failure() -> None:
    # A crashed case can store a very long error string; a single table cell taller than a
    # page makes fpdf2 raise. The cell text must be clipped so the report still renders.
    huge = "error: APIError: " + ("x " * 5000)
    run = _run("x", [CaseResult(id="c1", passed=False, failures=[huge], routed_intent="y" * 5000)])
    assert render_pdf([run])[:5] == b"%PDF-"
