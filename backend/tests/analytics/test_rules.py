"""Rule-based labeler (pure function) — no DB, no model. Verifies the strong-signal
boundary: a submitted request or a canonical hit is labeled deterministically; open
Q&A yields None (→ the model labels it)."""

from datetime import UTC, datetime

from app.domain.analytics.labels import label_by_rules
from app.domain.conversations.models import Conversation, Message


def _convo(*, messages: list[Message] | None = None) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(id="cnv_1", started_at=now, last_activity_at=now, messages=messages or [])


def _msg(content: str, *, canonical_answer_id: str | None = None) -> Message:
    return Message(
        id="msg_1",
        role="assistant",
        content=content,
        canonical_answer_id=canonical_answer_id,
        created_at=datetime.now(UTC),
    )


def test_submitted_request_labels_request_contact() -> None:
    labels = label_by_rules(_convo(), request_type="strategy_call", canonical_intents=[])
    assert labels is not None
    assert labels.intent == "request_contact" and labels.topic == "services"
    assert labels.method == "rules"


def test_request_prefers_canonical_topic_when_present() -> None:
    labels = label_by_rules(_convo(), request_type="strategy_call", canonical_intents=["pricing"])
    assert labels is not None
    assert labels.topic == "pricing" and labels.intent == "request_contact"


def test_canonical_hit_maps_topic_and_evaluate_intent() -> None:
    # Real seeded intent: data_security → topic "security", intent "evaluate".
    labels = label_by_rules(_convo(), request_type=None, canonical_intents=["data_security"])
    assert labels is not None
    assert labels.topic == "security" and labels.intent == "evaluate"


def test_portal_canonical_is_get_support() -> None:
    labels = label_by_rules(_convo(), request_type=None, canonical_intents=["portal_access"])
    assert labels is not None
    assert labels.topic == "portal" and labels.intent == "get_support"


def test_informational_canonical_intent_is_learn() -> None:
    labels = label_by_rules(_convo(), request_type=None, canonical_intents=["company_overview"])
    assert labels is not None
    assert labels.topic == "company" and labels.intent == "learn"


def test_unsupported_canonical_intent_defers_to_model() -> None:
    # "unsupported" carries no strong topic signal, so no rule fires (→ model labels it).
    labels = label_by_rules(_convo(), request_type=None, canonical_intents=["unsupported"])
    assert labels is None


def test_open_qa_returns_none_for_model() -> None:
    labels = label_by_rules(
        _convo(messages=[_msg("Here is some general info about our services.")]),
        request_type=None,
        canonical_intents=[],
    )
    assert labels is None
