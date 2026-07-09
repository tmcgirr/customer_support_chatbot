"""Hybrid conversation labeler: rules first, model for the residue.

Combines the deterministic rules (``labels.label_by_rules``) with a model fallback
for conversations that have no strong signal. Built fresh per labeling run so the
canonical id→intent map is fetched once and reused across the batch.

The model path is best-effort: a classify failure returns ``None`` so the job leaves
the conversation unlabeled and retries it next run — it never fails the batch or
dead-letters over a transient model outage.
"""

import asyncio

from app.agent.adapter import AdapterError, ModelAdapter
from app.core.logging import get_logger
from app.domain.analytics.labels import (
    CLASSIFY_INSTRUCTIONS,
    label_by_rules,
    parse_model_labels,
)
from app.domain.canonical.repository import CanonicalAnswerRepository
from app.domain.conversations.models import Conversation, ConversationLabels
from app.domain.requests.repository import RequestRepository

logger = get_logger("app.analytics.labeler")

# Cap the transcript sent to the classifier — recent turns carry the intent, and an
# unbounded transcript would waste tokens. Characters, not tokens (cheap + good enough).
_MAX_TRANSCRIPT_CHARS = 6000
# Hard cap on a single classify call so one slow response can't push the batch job past
# the worker's handler timeout. A timeout is treated like a model outage (retry next run).
_CLASSIFY_TIMEOUT_SECONDS = 12.0


class ConversationLabeler:
    def __init__(
        self,
        canonical: CanonicalAnswerRepository,
        requests: RequestRepository,
        adapter: ModelAdapter,
        *,
        classify_timeout: float = _CLASSIFY_TIMEOUT_SECONDS,
    ) -> None:
        self._canonical = canonical
        self._requests = requests
        self._adapter = adapter
        self._classify_timeout = classify_timeout
        self._intent_map: dict[str, str] | None = None  # canonical answer id → intent

    async def _canonical_intent_map(self) -> dict[str, str]:
        if self._intent_map is None:
            answers = await self._canonical.list_answers()
            self._intent_map = {a.id: a.intent for a in answers}
        return self._intent_map

    async def _canonical_intents(self, conversation: Conversation) -> list[str]:
        intent_map = await self._canonical_intent_map()
        intents: list[str] = []
        for message in conversation.messages:
            cid = message.canonical_answer_id
            if cid is not None and cid in intent_map:
                intents.append(intent_map[cid])
        return intents

    async def label(self, conversation: Conversation) -> ConversationLabels | None:
        """Label one conversation. Returns None ONLY when the residue path needed the
        model and the model call failed (→ retry next run)."""
        request_type = await self._requests.request_type_for_conversation(conversation.id)
        canonical_intents = await self._canonical_intents(conversation)
        rule_labels = label_by_rules(
            conversation, request_type=request_type, canonical_intents=canonical_intents
        )
        if rule_labels is not None:
            return rule_labels

        transcript = _transcript_text(conversation)
        if not transcript:
            # Nothing to read (e.g. an abandoned conversation with no user text) — a
            # rule couldn't fire and there's no signal for the model either.
            return parse_model_labels("")  # → topic/intent "other", method "model"
        try:
            raw = await asyncio.wait_for(
                self._adapter.classify(
                    instructions=CLASSIFY_INSTRUCTIONS, text=transcript, category="labeling"
                ),
                timeout=self._classify_timeout,
            )
        except (AdapterError, TimeoutError):
            # Transient model failure / slow response — leave unlabeled; retry next run.
            # (Bounding each call keeps the batch job under the worker handler timeout.)
            logger.info(
                "analytics.label.model_unavailable",
                extra={"context": {"conversation_id": conversation.id}},
            )
            return None
        return parse_model_labels(raw)


def _transcript_text(conversation: Conversation) -> str:
    """Flatten the transcript to ``role: content`` lines, newest-biased and capped.
    Only completed messages contribute (partials/failures carry no reliable intent)."""
    lines = [
        f"{m.role}: {m.content}"
        for m in conversation.messages
        if m.status == "completed" and m.content.strip()
    ]
    text = "\n".join(lines)
    if len(text) > _MAX_TRANSCRIPT_CHARS:
        # Keep the TAIL — the most recent turns best reflect what the visitor wanted.
        text = text[-_MAX_TRANSCRIPT_CHARS:]
    return text
