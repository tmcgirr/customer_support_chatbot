"""ConversationLabeler: rules short-circuit the model; the residue hits classify;
a classify failure yields None (retry next run). Uses lightweight repo fakes + the
FakeAdapter — no DB, no OpenAI."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.agent.adapter import AdapterError
from app.domain.analytics.labeler import ConversationLabeler
from app.domain.conversations.models import Conversation, Message
from tests.fakes import FakeAdapter


class _FakeCanonical:
    def __init__(self, answers: list[Any]) -> None:
        self._answers = answers

    async def list_answers(self) -> list[Any]:
        return self._answers


class _FakeRequests:
    def __init__(self, request_type: str | None = None) -> None:
        self._request_type = request_type

    async def request_type_for_conversation(self, conversation_id: str) -> str | None:
        return self._request_type


def _convo(messages: list[Message]) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(id="cnv_1", started_at=now, last_activity_at=now, messages=messages)


def _msg(role: str, content: str, *, canonical_answer_id: str | None = None) -> Message:
    return Message(
        id="msg",
        role=role,
        content=content,
        canonical_answer_id=canonical_answer_id,
        created_at=datetime.now(UTC),
    )


def _labeler(*, canonical: Any = None, requests: Any = None, adapter: Any = None) -> Any:
    return ConversationLabeler(
        canonical or _FakeCanonical([]),
        requests or _FakeRequests(),
        adapter or FakeAdapter(),
    )


async def test_rules_hit_skips_the_model() -> None:
    # A canonical answer for "pricing" was served — rules label it, model is never called.
    canonical = _FakeCanonical([SimpleNamespace(id="can_pricing", intent="pricing")])
    adapter = FakeAdapter()
    labeler = _labeler(canonical=canonical, adapter=adapter)
    convo = _convo([_msg("assistant", "Our pricing…", canonical_answer_id="can_pricing")])

    labels = await labeler.label(convo)

    assert labels is not None
    assert labels.topic == "pricing" and labels.intent == "evaluate" and labels.method == "rules"
    assert adapter.classify_calls == []  # model NOT consulted


async def test_residue_uses_the_model() -> None:
    adapter = FakeAdapter(classify_result='{"topic": "industry", "intent": "learn"}')
    labeler = _labeler(adapter=adapter)
    convo = _convo([_msg("user", "How does AI help manufacturing?")])

    labels = await labeler.label(convo)

    assert labels is not None
    assert labels.topic == "industry" and labels.intent == "learn" and labels.method == "model"
    assert len(adapter.classify_calls) == 1
    assert "manufacturing" in adapter.classify_calls[0]  # transcript reached the model


async def test_bad_model_json_degrades_to_other() -> None:
    adapter = FakeAdapter(classify_result="not json at all")
    labeler = _labeler(adapter=adapter)
    convo = _convo([_msg("user", "Something ambiguous.")])

    labels = await labeler.label(convo)

    assert labels is not None
    assert labels.topic == "other" and labels.intent == "other" and labels.method == "model"


async def test_classify_failure_returns_none_for_retry() -> None:
    adapter = FakeAdapter(classify_raises=AdapterError())
    labeler = _labeler(adapter=adapter)
    convo = _convo([_msg("user", "A question with no strong signal.")])

    assert await labeler.label(convo) is None  # left unlabeled → retried next run


async def test_request_signal_labels_request_contact() -> None:
    labeler = _labeler(requests=_FakeRequests(request_type="portal_support"))
    convo = _convo([_msg("user", "I need help logging into the portal.")])

    labels = await labeler.label(convo)

    assert labels is not None
    assert labels.intent == "request_contact" and labels.topic == "portal"
