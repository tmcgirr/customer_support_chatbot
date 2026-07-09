"""Self-contained HTML report for evaluation runs — a developer/test surface, opened
locally, deliberately NOT part of the chatbot or the admin app.

One run → a score card + per-case table (routing, latency, failures). Multiple runs →
a ranking table (score/latency) and a case×config DIFF matrix that highlights exactly which
cases a prompt/model change fixed or broke.
"""

import html

from eval.results import RunResult, rank


def _esc(value: object) -> str:
    return html.escape(str(value))


def _bar(score: float) -> str:
    pct = round(score * 100)
    hue = "var(--pass)" if score >= 0.999 else ("var(--warn)" if score >= 0.8 else "var(--fail)")
    return (
        f'<span class="bar"><span class="fill" style="width:{pct}%;background:{hue}"></span></span>'
        f"<span class='pct'>{pct}%</span>"
    )


def _ranking_table(runs: list[RunResult]) -> str:
    rows = []
    for i, r in enumerate(runs, 1):
        c = r.config
        fb = c.fallback_model or "—"
        rows.append(
            f"<tr><td class='num'>{i}</td><td><b>{_esc(c.name)}</b></td><td>{_esc(c.model)}</td>"
            f"<td>{_esc(c.prompt_version)}</td><td>{_esc(fb)}</td>"
            f"<td>{_bar(r.score)}</td><td class='num'>{r.passed}/{r.total}</td>"
            f"<td class='num'>{r.avg_latency_ms} ms</td></tr>"
        )
    return (
        "<h2>Ranking</h2><table><thead><tr><th>#</th><th>Config</th><th>Model</th>"
        "<th>Prompt</th><th>Fallback</th><th>Pass rate</th><th>Passed</th>"
        "<th>Avg latency</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _diff_matrix(runs: list[RunResult]) -> str:
    case_ids = sorted({c.id for r in runs for c in r.cases})
    passed_by = {r.config.name: {c.id: c.passed for c in r.cases} for r in runs}
    head = "".join(f"<th>{_esc(r.config.name)}</th>" for r in runs)
    rows = []
    for cid in case_ids:
        cells = []
        seen = []
        for r in runs:
            p = passed_by[r.config.name].get(cid)
            seen.append(p)
            if p is None:
                cells.append("<td class='skip'>–</td>")
            else:
                cells.append(f"<td class='{'ok' if p else 'no'}'>{'✓' if p else '✗'}</td>")
        # Highlight rows where configs DISAGREE (a fix or a regression between configs).
        differ = " class='differ'" if len({s for s in seen if s is not None}) > 1 else ""
        rows.append(f"<tr{differ}><td class='mono'>{_esc(cid)}</td>{''.join(cells)}</tr>")
    return (
        "<h2>Case × config</h2><p class='muted'>Highlighted rows are cases where the configs "
        "disagree — where a prompt/model change fixed or broke a case.</p>"
        f"<table class='matrix'><thead><tr><th>Case</th>{head}</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _run_detail(run: RunResult) -> str:
    c = run.config
    cats = "".join(
        f"<span class='chip'>{_esc(cat)} {p}/{t}</span>"
        for cat, (p, t) in run.by_category().items()
    )
    rows = []
    for case in run.cases:
        status = "<span class='ok'>PASS</span>" if case.passed else "<span class='no'>FAIL</span>"
        fails = "<br>".join(_esc(f) for f in case.failures) or "—"
        actions = ", ".join(_esc(a) for a in case.actions) or "—"
        rows.append(
            f"<tr><td class='mono'>{_esc(case.id)}</td><td>{status}</td>"
            f"<td class='mono'>{_esc(case.routed_intent or '—')}</td><td>{actions}</td>"
            f"<td class='num'>{case.latency_ms} ms</td><td class='fail-cell'>{fails}</td></tr>"
            f"<tr class='text-row'><td></td><td colspan='5'><details><summary>response</summary>"
            f"<pre>{_esc(case.text)}</pre></details></td></tr>"
        )
    return (
        f"<h2>{_esc(c.name)} — {_bar(run.score)} "
        f"<span class='muted'>({run.passed}/{run.total})</span></h2>"
        f"<p class='muted'>model <b>{_esc(c.model)}</b> · prompt <b>{_esc(c.prompt_version)}</b> · "
        f"fallback {_esc(c.fallback_model or '—')} · avg {run.avg_latency_ms} ms</p>"
        f"<p>{cats}</p>"
        "<table><thead><tr><th>Case</th><th>Status</th><th>Routed intent</th><th>Actions</th>"
        "<th>Latency</th><th>Failures</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


_CSS = """
:root{--pass:#1e7e34;--warn:#8a5a00;--fail:#b00020;--bg:#fff;--fg:#1a1a1a;--line:#e4e7eb;--muted:#667}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
 color:var(--fg);background:#f5f6f8;margin:0;padding:24px;line-height:1.4}
.wrap{max-width:1100px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.muted{color:var(--muted);font-size:13px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line);
 border-radius:6px;overflow:hidden;font-size:13px;margin-top:6px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top}
thead th{background:#eef1f4;font-weight:600;white-space:nowrap}
tr:last-child td{border-bottom:none}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.ok{color:var(--pass);font-weight:600}.no{color:var(--fail);font-weight:600}
.skip{color:var(--muted)}
tr.differ{background:#fff8e1}
.matrix td{text-align:center}
.fail-cell{color:var(--fail);font-size:12px}
.bar{display:inline-block;width:120px;height:12px;background:#eef1f4;border-radius:6px;
 overflow:hidden;vertical-align:middle;margin-right:6px}
.fill{display:block;height:100%}
.pct{font-variant-numeric:tabular-nums;font-size:12px}
.chip{display:inline-block;background:#eef1f4;border-radius:10px;padding:1px 8px;
 margin:2px 4px 2px 0;font-size:12px}
.text-row td{background:#fafbfc;border-bottom:1px solid var(--line)}
details summary{cursor:pointer;color:#1155cc;font-size:12px}
pre{white-space:pre-wrap;font-size:12px;margin:6px 0 0;color:#333}
"""


def render_html(runs: list[RunResult], *, title: str = "Cadre AI — Evaluation Report") -> str:
    if not runs:
        return f"<!doctype html><meta charset=utf-8><title>{_esc(title)}</title><p>No runs.</p>"
    ranked = rank(runs)
    stamp = ranked[0].generated_at.strftime("%Y-%m-%d %H:%M UTC")
    best = ranked[0]
    body = [
        f"<h1>{_esc(title)}</h1>",
        f"<p class='muted'>{stamp} · {best.total} golden cases · "
        f"{'comparing ' + str(len(runs)) + ' configs' if len(runs) > 1 else 'single run'}</p>",
    ]
    if len(runs) > 1:
        body.append(_ranking_table(ranked))
        body.append(_diff_matrix(ranked))
    for run in ranked:
        body.append(_run_detail(run))
    return (
        f"<!doctype html><html><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head>"
        f"<body><div class='wrap'>{''.join(body)}</div></body></html>"
    )
