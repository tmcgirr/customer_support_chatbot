"""Conversation topic/intent taxonomy + the deterministic (rule-based) labeler.

V1.5 analytics: after a conversation ends, we tag it with a **topic** (what it was
about) and an **intent** (what the visitor wanted). This is a HYBRID pipeline —
rules label the conversations we already have strong signal for (a canonical-answer
hit or a submitted request), cheaply and deterministically; everything else (open
Q&A, unresolved) is left for the model to label (``labeler.py``).

Counts only ever leave this layer — no message content is stored on the label, and
the whole thing runs off the worker, never on the request path (invariant #5, #2).
"""

from datetime import UTC, datetime

from app.domain.conversations.models import Conversation, ConversationLabels

# Fixed taxonomy. Keep these in sync with the model prompt below and the dashboard.
TOPICS: tuple[str, ...] = (
    "pricing",
    "security",
    "ai_maturity",
    "portal",
    "case_study",
    "services",
    "company",
    "industry",
    "other",
)
INTENTS: tuple[str, ...] = (
    "evaluate",  # weighing Cadre — pricing, security, maturity, case studies
    "get_support",  # existing-client / portal help
    "request_contact",  # asked to talk to a human (submitted a request)
    "learn",  # general information gathering
    "other",
)

# canonical_answers.intent (the `get_canonical_answer` arg) → (topic, visitor intent).
# Keyed by the ACTUAL seeded intents (scripts/seed_canonical.py / app/agent/tools.py).
# "unsupported" and any unmapped intent carry no strong signal → the model labels them.
_CANONICAL_LABEL: dict[str, tuple[str, str]] = {
    "pricing": ("pricing", "evaluate"),
    "data_security": ("security", "evaluate"),
    "ai_maturity_index": ("ai_maturity", "evaluate"),
    "case_study": ("case_study", "evaluate"),
    "llm_selection": ("services", "evaluate"),
    "portal_access": ("portal", "get_support"),
    "company_overview": ("company", "learn"),
    "service_overview": ("services", "learn"),
    "industry_fit": ("industry", "learn"),
    "strategy_call": ("services", "evaluate"),
}

# RequestType → topic when a request was submitted but no canonical topic is clearer.
# Escalation isn't itself a topic, so it defers to any canonical topic, else "other".
_REQUEST_TOPIC: dict[str, str] = {
    "strategy_call": "services",
    "portal_support": "portal",
    "human_escalation": "other",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _primary_canonical_label(canonical_intents: list[str]) -> tuple[str, str] | None:
    """The (topic, intent) of the first canonical intent that maps to a concrete label —
    a conversation about pricing that also grazed a generic intent reads as pricing."""
    for intent in canonical_intents:
        label = _CANONICAL_LABEL.get(intent)
        if label is not None:
            return label
    return None


def label_by_rules(
    conversation: Conversation,
    *,
    request_type: str | None,
    canonical_intents: list[str],
) -> ConversationLabels | None:
    """Label a conversation from signals we already captured, or return ``None`` when
    there is no strong signal (→ the model labels it).

    Strong signal = a submitted request (the visitor asked for a human) OR a
    canonical-answer hit (a sensitive/structured topic). Open Q&A and
    unresolved-only conversations return None so the model can read the transcript.
    """
    canonical = _primary_canonical_label(canonical_intents)

    if request_type is not None:
        # The visitor asked to be contacted — intent is unambiguous; prefer a canonical
        # topic if one was discussed, else derive from the request type.
        topic = canonical[0] if canonical is not None else _REQUEST_TOPIC.get(request_type, "other")
        return _labels(topic, "request_contact")

    if canonical is not None:
        # A sensitive/structured topic served from a canonical answer.
        return _labels(canonical[0], canonical[1])

    return None  # no strong signal → defer to the model labeler


def _labels(topic: str, intent: str) -> ConversationLabels:
    return ConversationLabels(topic=topic, intent=intent, method="rules", labeled_at=_now())


# --- Model-residue labeling (parsing the model's structured answer) ------------

# Instruction block for the classifier. The model sees ONLY the transcript text and
# must answer with one topic + one intent from the fixed taxonomy.
CLASSIFY_INSTRUCTIONS = (
    "You classify a customer-support chat transcript for internal analytics. "
    'Respond with ONLY a compact JSON object: {"topic": <topic>, "intent": <intent>}. '
    f"topic must be exactly one of: {', '.join(TOPICS)}. "
    f"intent must be exactly one of: {', '.join(INTENTS)}. "
    "Pick the single best fit for what the visitor was asking about (topic) and what "
    "they wanted (intent). Use 'other' only when nothing else fits. Output no prose."
)


def parse_model_labels(raw: str) -> ConversationLabels:
    """Validate the model's JSON answer against the taxonomy. Any malformed/unknown
    value degrades to 'other' rather than raising — a bad label must never fail the
    batch (the conversation is still labeled, just coarsely)."""
    import json

    topic, intent = "other", "other"
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            cand_topic = str(data.get("topic", "")).strip().lower()
            cand_intent = str(data.get("intent", "")).strip().lower()
            if cand_topic in TOPICS:
                topic = cand_topic
            if cand_intent in INTENTS:
                intent = cand_intent
    except (json.JSONDecodeError, TypeError):
        pass
    return ConversationLabels(topic=topic, intent=intent, method="model", labeled_at=_now())
