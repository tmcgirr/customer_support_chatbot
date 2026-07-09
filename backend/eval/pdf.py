"""PDF evaluation report — a downloadable, shareable/archivable artifact for a tester.

Purpose-built (not an HTML render): a ranking table when comparing configs, then a per-config
score card + per-case table (status, routed intent, latency, failures). Pure-Python via fpdf2
(no system deps). The richer interactive view stays the HTML report; this is the hand-off file.
"""

from fpdf import FPDF
from fpdf.fonts import FontFace

from eval.results import RunResult, rank

_GREEN = (30, 126, 52)
_RED = (176, 0, 32)
_MUTED = (100, 100, 110)
_HEADER_BG = (238, 241, 244)


def _safe(text: object) -> str:
    """fpdf2's core fonts are latin-1 only; replace anything outside it so a stray unicode
    char in a model response can never crash the report."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def _heading(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 7, _safe(text), new_x="LMARGIN", new_y="NEXT")


def _ranking(pdf: FPDF, runs: list[RunResult]) -> None:
    _heading(pdf, "Ranking")
    pdf.set_font("Helvetica", size=8)
    with pdf.table(
        col_widths=(8, 26, 34, 22, 16, 16, 18),
        text_align=("CENTER", "LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"),
        headings_style=FontFace(emphasis="BOLD", fill_color=_HEADER_BG),
    ) as table:
        table.row(["#", "Config", "Model", "Prompt", "Pass %", "Passed", "Avg ms"])
        for i, r in enumerate(runs, 1):
            table.row(
                [
                    str(i),
                    _safe(r.config.name),
                    _safe(r.config.model),
                    _safe(r.config.prompt_version),
                    f"{round(r.score * 100)}%",
                    f"{r.passed}/{r.total}",
                    str(r.avg_latency_ms),
                ]
            )
    pdf.ln(4)


def _run_section(pdf: FPDF, run: RunResult) -> None:
    c = run.config
    _heading(pdf, f"{c.name} - {round(run.score * 100)}% ({run.passed}/{run.total})")
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(*_MUTED)
    pdf.cell(
        0,
        5,
        _safe(f"model {c.model}  -  prompt {c.prompt_version}  -  avg {run.avg_latency_ms} ms"),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)
    pdf.set_font("Helvetica", size=8)
    with pdf.table(
        col_widths=(20, 12, 26, 12, 82),
        text_align=("LEFT", "CENTER", "LEFT", "RIGHT", "LEFT"),
        headings_style=FontFace(emphasis="BOLD", fill_color=_HEADER_BG),
    ) as table:
        table.row(["Case", "Status", "Routed intent", "ms", "Failures"])
        for case in run.cases:
            row = table.row()
            row.cell(_safe(case.id))
            row.cell(
                "PASS" if case.passed else "FAIL",
                style=FontFace(color=_GREEN if case.passed else _RED, emphasis="BOLD"),
            )
            row.cell(_safe(case.routed_intent or "-"))
            row.cell(str(case.latency_ms))
            row.cell(_safe("; ".join(case.failures) or "-"))
    pdf.ln(4)


def render_pdf(runs: list[RunResult]) -> bytes:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title("Cadre AI - Evaluation Report")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Cadre AI - Evaluation Report", new_x="LMARGIN", new_y="NEXT")

    if not runs:
        pdf.set_font("Helvetica", size=11)
        pdf.cell(0, 8, "No runs.")
        return bytes(pdf.output())

    ranked = rank(runs)
    stamp = ranked[0].generated_at.strftime("%Y-%m-%d %H:%M UTC")
    label = f"comparing {len(runs)} configs" if len(runs) > 1 else "single run"
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(*_MUTED)
    pdf.cell(
        0,
        6,
        _safe(f"{stamp}  -  {ranked[0].total} golden cases  -  {label}"),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    if len(ranked) > 1:
        _ranking(pdf, ranked)
    for run in ranked:
        _run_section(pdf, run)
    return bytes(pdf.output())
