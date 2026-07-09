# Analytics & insights

> **In one line:** A worker-owned analytics suite that turns ended conversations into topic/intent labels, per-conversation summaries, a conversion funnel, and clustered "what visitors keep asking" insight reports — including a ranked knowledge-gap board whose proposed FAQs flow straight into the canonical approval queue.

**Status:** Live on staging (one piece — dashboard *trends* — is in progress; see below)  ·  **Introduced:** V1.5

## What it is
This is the reporting layer over the chatbot's traffic. After a conversation ends, background jobs tag it (topic + visitor intent), write a short TL;DR, and — on a daily/weekly/monthly cadence — cluster similar visitor questions into an **insights report** that flags which themes we already answer and which we don't. A cross-report **knowledge-gap ranking** then surfaces the biggest, most-persistent unanswered themes, and the pipeline can auto-draft a proposed FAQ for each one. Everything is read-only with respect to the visitor: it never touches the live chat, and every proposed answer still passes through the human [canonical-answers](canonical-answers.md) draft→approved gate before it is ever served.

## Why it exists
The POC could answer questions but was blind to them in aggregate — operators had no way to see demand, spot coverage gaps, or prioritize new content. V1.5 adds that visibility so a PM/content owner can answer "what are people asking, what do we miss, and what should we add next?" from data, not anecdote. Two decisions shape it: (1) all of it runs **off the request path on the worker** (architecture invariant #2), so analytics can never slow or destabilize a live turn; and (2) the model stays **read-only** — it labels, summarizes, and *proposes*, but a human approves every FAQ, reusing the existing canonical draft→approved lifecycle rather than inventing a second publishing path (ADR-008; invariants #8, #12).

## How it works
Five cooperating pieces. **Three are scheduled worker jobs** that touch the model only through the adapter's `classify`/`embed` boundary (labeling, insights, summaries — provider isolation, invariant #4); **two are request-time Mongo reads with no worker job and no model call** (the funnel aggregation and the knowledge-gap ranking):

### 1. Topic/intent labeling
A **hybrid** labeler tags each ended conversation with one `topic` (what it was about) and one `intent` (what the visitor wanted) from a fixed taxonomy. Rules fire first and cheaply for conversations we already have strong signal on — a canonical-answer hit or a submitted contact request map deterministically to a label; everything left over (open Q&A) is sent to the model for a single classify call. Model failures leave the conversation unlabeled to retry next run — they never fail the batch or dead-letter. The `label_conversations` job runs hourly (batch 200, ~30s wall-clock budget, FIFO drain). Labels feed the dashboard's *Top topics* / *Visitor intent* breakdowns and every funnel split.

### 2. Conversation insights (clustering + coverage/gap + proposed FAQs)
Per period the pipeline: picks one representative question per conversation (a heuristic — the first unsupported question if any, else the first substantive user message; **no** model call) → batch-embeds the questions → clusters near-identical ones (see cluster.py) → for each *notable* cluster (≥ `insights_min_cluster_size`, default 3) asks the model for a theme label, a **coverage** verdict (`covered` / `unclear` / `missing`, judged against the list of approved canonical topics), and a proposed unified Q/A. Cost scales with cluster count, not conversation count. Reports come in **daily / weekly / monthly** horizons (they overlap by design). The scheduled run generates each horizon's last *complete* period just after its boundary; a manual "Run now" regenerates the current in-progress period. Report ids are `"<type>:<key>"` (e.g. `daily:2026-07-08`), so re-runs overwrite idempotently. **Auto-drafting is daily-only**: when a cluster is `missing`/`unclear`, the pipeline upserts a `draft` canonical answer (deterministic `insight_…` intent derived from the stable representative question, so retries dedupe to one draft) and writes an audit record *before* creating it — but it stays a draft until a human approves it.

### 3. Knowledge-gap ranking (newest)
`rank_gaps()` (gaps.py) is a pure **read-side view** over already-stored reports — no model calls, no new storage. It folds the **non-covered** (`missing`/`unclear`) clusters across the last N **daily** reports into one ranked list so the questions visitors keep asking that we answer poorly rise to the top. Each gap merges cross-day by the stable analytics topic (falling back to the normalized theme label) and is ranked by **magnitude** (`total_asked` = Σ cluster size across occurrences), then **persistence** (`days_seen` = distinct daily reports it appeared in), then a stable key. It is daily-only on purpose: weekly/monthly reports overlap the same conversations and would double-count. Each gap carries forward the proposed FAQ and its `proposed_canonical_intent`, so a PM can approve the drafted answer directly from the gap row. Served at `GET /insights/gaps?window=14&limit=20`; rendered at the top of the admin Insights view.

### 4. Funnel
A conversion funnel — **visited → asked → engaged → requested** — computed live from conversation counts by a single Mongo aggregation (`ConversationRepository.funnel`). It is **monotone by construction**: a later stage always implies the earlier ones (a single-turn conversation that converted is still folded into *asked* and *engaged*), so bars can never invert. Returned overall and broken down by `labels.topic` and `labels.intent`; unlabeled conversations bucket as `unset`.

### 5. Summaries
A per-conversation TL;DR — `{tldr, key_points}` — so admins can scan the conversation list without opening each transcript. One model classify call per ended conversation; the `summarize_conversations` job runs hourly (batch 100, ~30s budget), is idempotent, and a model failure leaves it un-summarized to retry (never dead-letters). Summaries are shown (PII-masked) on the conversation list and detail.

See [doc 03](../03_Architecture_and_Decision_Records.md) for the worker/read-only invariants and [doc 04 §4](../04_API_and_Data_Contracts.md) for the admin API + §10 masking rules.

## Key files
- `backend/app/domain/analytics/labels.py` — topic/intent taxonomy, the deterministic rule labeler, and the model-classify prompt + parser.
- `backend/app/domain/analytics/labeler.py` — hybrid orchestration: rules first, model for the residue; timeout-bounded, failure = retry next run.
- `backend/app/domain/analytics/summarizer.py` — per-conversation `{tldr, key_points}` digest.
- `backend/app/domain/insights/service.py` — the full insights pipeline (extract → embed → cluster → analyze → daily auto-draft → summarize → store), plus scheduled vs. manual entry points.
- `backend/app/domain/insights/cluster.py` — deterministic union-find cosine clustering (pure Python, no numpy).
- `backend/app/domain/insights/gaps.py` — `rank_gaps()`: the cross-report knowledge-gap aggregation/ranking.
- `backend/app/domain/insights/{models,periods,repository}.py` — report/cluster models, calendar-period math, and the idempotent report store.
- `backend/app/domain/conversations/repository.py` — the `funnel()` aggregation, the labeled/summarized-conversation queries, and `list_ended_in_window` (report membership).
- `backend/app/domain/aggregates/repository.py` — daily count snapshots (`daily_aggregates`) that back the dashboard + trends series.
- `backend/app/domain/jobs/tasks.py` — the worker task functions (`run_label_conversations`, `run_summarize_conversations`, `run_generate_insights`, `run_daily_aggregates`).
- `backend/app/api/admin/router.py` — the admin endpoints (dashboard, funnel, insights, gaps, trends) with default PII masking.
- `frontend/src/admin/{Insights,Dashboard,Funnel}.tsx` — the three admin screens.

## Interfaces
- **Worker jobs** (scheduled in `app/worker.py`): `label_conversations` (hourly), `summarize_conversations` (hourly), `generate_insights` (hourly boundary check; also a manual mode), `daily_aggregates` (daily).
- **Admin API** (all admin-authed, read-only unless noted): `GET /dashboard` (totals + by-status/outcome/topic/intent), `GET /funnel`, `GET /insights` (latest), `GET /insights/reports` (list/picker), `GET /insights/reports/{id}`, `GET /insights/gaps`, `POST /insights/run` (admin-only, audited, dedup-guarded), `GET /dashboard/trends` (in progress — see below).
- **Admin screens:** Dashboard (KPIs + breakdown tables), Funnel (overall + by topic/intent), Insights (gap board + report picker + cluster cards with one-click **Approve FAQ**).
- **Model tools:** none. Analytics never touches the read-only chat tools; it calls the adapter's `classify`/`embed` only.

## Status & limitations
- **Live on staging:** labeling, summaries, the funnel, insights reports (daily/weekly/monthly + manual run), daily auto-drafted proposed FAQs into the canonical queue, and the knowledge-gap board are all built and running on the worker.
- **In progress — dashboard *trends*:** the backend `GET /dashboard/trends` endpoint + `TrendPoint`/`TrendsResponse` models, the `AggregatesRepository` daily-snapshot feed, an admin `getTrends()` client method, and a `TrendChart` component all exist, but they are not yet rendered by a dashboard screen — trends is mid-integration, so treat it as not-yet-shipped.
- **Model-dependent, best-effort:** clustering/labeling/summaries depend on live embed/classify calls; on a provider outage the affected report is skipped or the conversation left un-annotated and retried — no dead-letter, but data can lag.
- **Sampling at scale:** an insights run analyzes at most `insights_batch_limit` (300) conversations per period; a busier period reports the true total alongside the analyzed count so a sample is never mistaken for the whole.
- **PII by default:** verbatim visitor text in admin analytics — summaries, cluster/gap questions, theme labels, and proposed FAQ *questions* — is masked; unmasking is the separate audited per-record reveal path (invariant #12, doc 04 §10). (Model-*generated* proposed answers are not verbatim visitor text and are shown as written.) No message content ever reaches logs (invariant #5).
- **Heuristics, not ground truth:** representative-question extraction, the similarity threshold (0.82), and the min cluster size (3) are tunable heuristics; labels/coverage/proposals are model judgments meant to guide a human, not to auto-publish.

## Future & scaling
- **Ship trends:** render the existing `getTrends()` client + `TrendChart` on the dashboard (KPI deltas + the daily-snapshot series) — the data and component layers exist; only the screen wiring remains.
- **Gap → content loop metrics:** the gap board already links a proposed FAQ to its canonical draft intent; a natural next step is closing the loop by tracking which gaps were approved and whether they shrink in later reports.
- **Clustering headroom:** the pure-Python O(n²) pairwise clustering is fine for a capped few-hundred-question batch; higher volume would want a vector-index/ANN or incremental clustering rather than a bigger batch cap.
- **Richer taxonomy:** topic/intent is a small fixed list kept in sync with the prompt and dashboard; expanding it (or making it configurable) would sharpen the funnel and gap merge keys.
- **Config-driven cadence:** horizons and thresholds are already settings (`insights_enable_*`, `insights_similarity_threshold`, budgets), so tuning is a config change, not a code change — a good lever once production traffic exists.

## Related
- [canonical answers](canonical-answers.md) — the draft→approved gate that every proposed FAQ (and every auto-draft from insights) flows through.
- [knowledge base](knowledge-retrieval.md) — the Vector Store side of "coverage"; a gap is what neither canonical answers nor the KB answer well.
- [worker & jobs](worker-and-jobs.md) — the scheduler/retry/dead-letter machinery these jobs run on.
- [admin console](admin-roles-and-audit.md) — the surrounding admin SPA, auth roles, and the audited reveal path.
- [doc 03 — ADR-008](../03_Architecture_and_Decision_Records.md) (canonical answers) and the read-only/worker invariants; [doc 04 §4 + §10](../04_API_and_Data_Contracts.md) — admin API contracts and masking.
