"""Async conversation summarizer (V1.5): a short {tldr, key_points} digest per ended
conversation so admins can scan the list without opening each transcript.

Worker-owned, never on the request path. One model call per conversation, per-call
timeout-bounded; a model failure returns None so the conversation is left un-summarized and
retried next run (never dead-letters). No PII in logs — the transcript goes to the model
(allowed) but is never logged (invariant #5, #2).
"""

import asyncio
import json
from datetime import datetime

from app.agent.adapter import AdapterError, ModelAdapter
from app.core.logging import get_logger
from app.domain.conversations.models import Conversation, ConversationDigest

logger = get_logger("app.analytics.summarizer")

_MAX_TRANSCRIPT_CHARS = 6000
_CLASSIFY_TIMEOUT_SECONDS = 12.0

SUMMARY_INSTRUCTIONS = (
    "You summarize a customer-support chat transcript for an internal admin console. "
    'Respond with ONLY a JSON object: {"tldr": <one or two sentences: what the visitor '
    'wanted and how it went>, "key_points": [<up to 4 short bullet strings: the ask, any '
    "specifics, the outcome>]}. Be concise and factual, no preamble, no invented details."
)


def _transcript(conversation: Conversation) -> str:
    lines = [
        f"{m.role}: {m.content}"
        for m in conversation.messages
        if m.status == "completed" and m.content.strip()
    ]
    text = "\n".join(lines)
    return text[-_MAX_TRANSCRIPT_CHARS:] if len(text) > _MAX_TRANSCRIPT_CHARS else text


def parse_digest(raw: str, now: datetime) -> ConversationDigest:
    """Validate the model's JSON into a digest; any malformed output degrades to a minimal
    digest rather than raising (a bad summary must never fail the batch)."""
    tldr, points = "", []
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            tldr = str(data.get("tldr", "")).strip()[:500]
            raw_points = data.get("key_points", [])
            if isinstance(raw_points, list):
                points = [str(p).strip()[:200] for p in raw_points if str(p).strip()][:6]
    except (json.JSONDecodeError, TypeError):
        pass
    return ConversationDigest(
        tldr=tldr or "Summary unavailable.", key_points=points, summarized_at=now
    )


class ConversationSummarizer:
    def __init__(
        self, adapter: ModelAdapter, *, classify_timeout: float = _CLASSIFY_TIMEOUT_SECONDS
    ) -> None:
        self._adapter = adapter
        self._classify_timeout = classify_timeout

    async def summarize(
        self, conversation: Conversation, *, now: datetime
    ) -> ConversationDigest | None:
        """Return a digest, or None ONLY when the model call fails (retry next run)."""
        transcript = _transcript(conversation)
        if not transcript:
            # message_count>=1 but no usable content — mark it done so it isn't re-scanned.
            return ConversationDigest(
                tldr="No summarizable content.", key_points=[], summarized_at=now
            )
        try:
            raw = await asyncio.wait_for(
                self._adapter.classify(
                    instructions=SUMMARY_INSTRUCTIONS, text=transcript, category="summary"
                ),
                timeout=self._classify_timeout,
            )
        except (AdapterError, TimeoutError):
            logger.info(
                "summarize.model_unavailable",
                extra={"context": {"conversation_id": conversation.id}},
            )
            return None
        return parse_digest(raw, now)
