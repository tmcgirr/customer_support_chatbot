"""Insights pipeline: turn a period's ended conversations into a report.

extract representative question (heuristic, no model call) → batch-embed → cluster
(in memory) → per notable cluster: LLM name + coverage + proposed answer → (daily only)
auto-draft the proposal into the canonical draft→approved queue → LLM summary → store.

Cost scales with CLUSTER count (one embed call + one LLM call per notable cluster + one
summary), not conversation count. Provider-isolated (adapter only), no PII in logs, and the
model is read-only — it never publishes; a human approves every proposed FAQ (invariant #8, #12).
"""

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from app.agent.adapter import AdapterError, ModelAdapter
from app.core import ids
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.audit.repository import AuditRepository
from app.domain.canonical.models import CanonicalAnswer
from app.domain.canonical.repository import CanonicalAnswerRepository
from app.domain.conversations.models import Conversation
from app.domain.conversations.repository import ConversationRepository
from app.domain.insights.cluster import cluster_by_similarity
from app.domain.insights.models import (
    Coverage,
    InsightsReport,
    ProposedAnswer,
    QuestionCluster,
)
from app.domain.insights.periods import Period, current_period, last_complete_period
from app.domain.insights.repository import InsightsReportRepository

logger = get_logger("app.insights")

_COVERAGES: tuple[Coverage, ...] = ("covered", "unclear", "missing")
_MAX_SAMPLES = 5  # verbatim sample questions kept per cluster

_ANALYZE_INSTRUCTIONS = (
    "You analyze a cluster of similar visitor questions from a consulting firm's support "
    "chatbot. Topics we ALREADY have approved answers for are listed. Respond with ONLY a "
    'JSON object: {"label": <3-6 word theme>, "coverage": "covered|unclear|missing", '
    '"proposed_question": <one unified question>, "proposed_answer": <a concise suggested '
    "answer, or empty string if already covered>}. coverage=covered if our approved topics "
    "already answer it, unclear if only partially, missing if not at all. Output no prose."
)

_SUMMARY_INSTRUCTIONS = (
    "You are writing a short internal insights brief for a support chatbot. Given the "
    "notable question clusters (theme, count, coverage) for the period, write 3-6 concise "
    "bullet points covering: the biggest demand signals, the clearest coverage gaps (what "
    "we should add to the FAQ/knowledge base), and any roadmap or competitor signals. Be "
    "specific and quantitative where possible. No preamble, no PII."
)


@dataclass(frozen=True)
class _Analysis:
    label: str
    coverage: Coverage
    proposed_question: str
    proposed_answer: str


def extract_question(conversation: Conversation) -> str | None:
    """The representative question of a conversation, heuristically (no model call):
    the first verbatim unsupported question if any (the clearest unmet ask), else the
    first substantive user message."""
    if conversation.unsupported_questions:
        q = conversation.unsupported_questions[0].question.strip()
        if q:
            return q
    for message in conversation.messages:
        if message.role == "user" and message.status == "completed":
            text = message.content.strip()
            if len(text) >= 8:  # skip trivial "hi"/"ok"
                return text
    return None


def _dominant_topic(conversations: list[Conversation]) -> str | None:
    topics = [c.labels.topic for c in conversations if c.labels is not None]
    if not topics:
        return None
    return Counter(topics).most_common(1)[0][0]


def _parse_analysis(raw: str, *, fallback_label: str) -> _Analysis:
    label, coverage, pq, pa = fallback_label, "unclear", "", ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            label = (str(data.get("label", "")).strip() or fallback_label)[:100]
            cand = str(data.get("coverage", "")).strip().lower()
            if cand in _COVERAGES:
                coverage = cand
            pq = str(data.get("proposed_question", "")).strip()[:500]
            pa = str(data.get("proposed_answer", "")).strip()[:2000]
    except (json.JSONDecodeError, TypeError):
        pass
    return _Analysis(label=label, coverage=coverage, proposed_question=pq, proposed_answer=pa)  # type: ignore[arg-type]


def _proposed_intent(label: str) -> str:
    """Deterministic canonical intent for a themed proposal, so re-running a period (or a
    recurring theme with the same label) upserts ONE draft rather than duplicating."""
    norm = " ".join(label.lower().split())
    return f"insight_{hashlib.sha1(norm.encode()).hexdigest()[:12]}"


class InsightsService:
    def __init__(
        self,
        conversations: ConversationRepository,
        canonical: CanonicalAnswerRepository,
        audit: AuditRepository,
        reports: InsightsReportRepository,
        adapter: ModelAdapter,
        settings: Settings,
    ) -> None:
        self._conversations = conversations
        self._canonical = canonical
        self._audit = audit
        self._reports = reports
        self._adapter = adapter
        self._settings = settings

    def _enabled_types(self) -> list[str]:
        s = self._settings
        out = []
        if s.insights_enable_daily:
            out.append("daily")
        if s.insights_enable_weekly:
            out.append("weekly")
        if s.insights_enable_monthly:
            out.append("monthly")
        return out

    async def ensure_latest(self, now: datetime) -> list[str]:
        """Scheduled path: for each enabled horizon, generate the last COMPLETE period's
        report if it doesn't exist yet (fires just after a period boundary; idempotent).
        A shared wall-clock budget bounds the WHOLE run — any horizon not reached is
        picked up next tick (it still doesn't exist), so the job never runs past the
        worker's job timeout."""
        deadline = time.monotonic() + self._settings.insights_time_budget_seconds
        generated = []
        for period_type in self._enabled_types():
            if time.monotonic() >= deadline:
                break
            period = last_complete_period(period_type, now)  # type: ignore[arg-type]
            if await self._reports.get(period.report_id) is None:
                report = await self.generate(period, now=now, deadline=deadline)
                if report is not None:
                    generated.append(period.report_id)
        return generated

    async def refresh_current(self, now: datetime) -> list[str]:
        """Manual path: (re)generate the CURRENT in-progress period for each horizon,
        bounded by one shared budget across all horizons (best-effort under the timeout)."""
        deadline = time.monotonic() + self._settings.insights_time_budget_seconds
        generated = []
        for period_type in self._enabled_types():
            if time.monotonic() >= deadline:
                break
            period = current_period(period_type, now)  # type: ignore[arg-type]
            report = await self.generate(period, now=now, deadline=deadline)
            if report is not None:
                generated.append(period.report_id)
        return generated

    async def generate(
        self, period: Period, *, now: datetime, deadline: float | None = None
    ) -> InsightsReport | None:
        """Build (and store) the report for one period. ``deadline`` (a shared monotonic
        cap for the whole job) bounds the per-cluster LLM loop. Returns None only if
        embeddings are unavailable (retry next run); an empty period still writes a report."""
        conversations = await self._conversations.list_ended_in_window(
            period.start, period.end, limit=self._settings.insights_batch_limit
        )
        pairs: list[tuple[Conversation, str]] = []
        for convo in conversations:
            question = extract_question(convo)
            if question is not None:
                pairs.append((convo, question))

        if not pairs:
            return await self._store_empty(period, now, len(conversations))

        questions = [q for _, q in pairs]
        try:
            embeddings = await self._adapter.embed(questions)
        except AdapterError:
            logger.warning(
                "insights.embed_unavailable", extra={"context": {"period": period.report_id}}
            )
            return None  # transient — the scheduled run retries next tick

        index_groups = cluster_by_similarity(
            embeddings, threshold=self._settings.insights_similarity_threshold
        )
        coverage_context = await self._coverage_context()
        # Auto-draft proposals ONLY from the daily run, so weekly/monthly (which overlap
        # daily) can't spam the canonical queue with duplicates of the same theme.
        create_drafts = period.type == "daily"

        # Fall back to a per-report budget when called directly (tests); the job passes a
        # shared deadline so the whole run stays under the worker timeout.
        if deadline is None:
            deadline = time.monotonic() + self._settings.insights_time_budget_seconds
        clusters: list[QuestionCluster] = []
        for members in index_groups:
            if len(members) < self._settings.insights_min_cluster_size:
                continue  # long tail — not surfaced individually
            member_convos = [pairs[i][0] for i in members]
            samples = [questions[i] for i in members[:_MAX_SAMPLES]]
            representative = questions[members[0]]
            analysis = await self._analyze(samples, coverage_context)
            proposed = None
            if analysis.coverage in ("missing", "unclear"):
                proposed = await self._propose(
                    analysis, representative, now=now, create_draft=create_drafts
                )
            clusters.append(
                QuestionCluster(
                    label=analysis.label,
                    representative_question=representative,
                    sample_questions=samples,
                    size=len(members),
                    dominant_topic=_dominant_topic(member_convos),
                    coverage=analysis.coverage,
                    conversation_ids=[c.id for c in member_convos],
                    proposed=proposed,
                )
            )
            if time.monotonic() >= deadline:
                break

        summary = await self._summarize(period, len(conversations), clusters)
        report = InsightsReport(
            id=period.report_id,
            period_type=period.type,
            period_key=period.key,
            generated_at=now,
            window_start=period.start,
            window_end=period.end,
            conversations_analyzed=len(conversations),
            clusters=clusters,
            summary=summary,
        )
        await self._reports.record(report)
        return report

    async def _store_empty(self, period: Period, now: datetime, analyzed: int) -> InsightsReport:
        report = InsightsReport(
            id=period.report_id,
            period_type=period.type,
            period_key=period.key,
            generated_at=now,
            window_start=period.start,
            window_end=period.end,
            conversations_analyzed=analyzed,
            clusters=[],
            summary="No conversations with questions to analyze in this period.",
        )
        await self._reports.record(report)
        return report

    async def _coverage_context(self) -> str:
        """Human-readable names of the APPROVED answers, so the model can tell whether a
        cluster is already covered. Only approved (served) content counts as coverage."""
        answers = await self._canonical.list_answers()
        names = sorted({a.name for a in answers if a.status == "approved"})
        return ", ".join(names) if names else "(none)"

    async def _analyze(self, samples: list[str], coverage_context: str) -> _Analysis:
        prompt = (
            f"Approved topics we already cover: {coverage_context}\n\n"
            f"Cluster questions:\n" + "\n".join(f"- {q}" for q in samples)
        )
        try:
            raw = await self._adapter.classify(instructions=_ANALYZE_INSTRUCTIONS, text=prompt)
        except AdapterError:
            return _Analysis(
                label=samples[0][:100], coverage="unclear", proposed_question="", proposed_answer=""
            )
        return _parse_analysis(raw, fallback_label=samples[0][:100])

    async def _summarize(
        self, period: Period, analyzed: int, clusters: list[QuestionCluster]
    ) -> str:
        if not clusters:
            return "No notable question clusters in this period."
        listing = "\n".join(
            f"- {c.label} (asked {c.size}×, coverage: {c.coverage})" for c in clusters
        )
        prompt = (
            f"Period: {period.type} {period.key} · {analyzed} conversations.\n"
            f"Notable clusters:\n{listing}"
        )
        try:
            return (
                await self._adapter.classify(instructions=_SUMMARY_INSTRUCTIONS, text=prompt)
            ).strip()
        except AdapterError:
            return "Insights summary is temporarily unavailable; cluster data below is complete."

    async def _propose(
        self, analysis: _Analysis, representative: str, *, now: datetime, create_draft: bool
    ) -> ProposedAnswer:
        question = analysis.proposed_question or representative
        answer = analysis.proposed_answer
        if not create_draft:
            return ProposedAnswer(question=question, answer=answer, canonical_draft_intent=None)

        intent = _proposed_intent(analysis.label)
        existing = await self._canonical.get(intent)
        if existing is not None:
            # Already proposed (draft) or handled (approved) — never re-create or overwrite
            # (upsert would not downgrade an approved answer, but we also don't churn drafts).
            draft_intent = intent if existing.status != "approved" else None
            return ProposedAnswer(
                question=question, answer=answer, canonical_draft_intent=draft_intent
            )

        await self._canonical.upsert(
            CanonicalAnswer(
                id=ids.canonical_answer_id(),
                name=analysis.label[:100],
                intent=intent,
                content=answer or "(proposed by insights — edit before approving)",
                status="draft",  # never served until a human approves (invariant #8)
                owner="insights",
                effective_date=now,
                review_date=now,
            )
        )
        await self._audit.record(
            actor="system:insights",
            role="system",
            action="propose_faq",
            target_type="canonical_answer",
            target_id=intent,
            reason="auto-drafted from a common uncovered question cluster",
        )
        return ProposedAnswer(question=question, answer=answer, canonical_draft_intent=intent)
