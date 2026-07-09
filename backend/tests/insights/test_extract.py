"""Heuristic question extraction + proposal-intent determinism (pure)."""

from datetime import UTC, datetime

from app.domain.conversations.models import Conversation, Message, UnsupportedQuestion
from app.domain.insights.service import _proposed_intent, extract_question


def _convo(**kw: object) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(id="cnv", started_at=now, last_activity_at=now, **kw)  # type: ignore[arg-type]


def _msg(role: str, content: str) -> Message:
    return Message(id="m", role=role, content=content, created_at=datetime.now(UTC))


def test_prefers_unsupported_question() -> None:
    convo = _convo(
        unsupported_questions=[
            UnsupportedQuestion(question="Do you support X?", at=datetime.now(UTC))
        ],
        messages=[_msg("user", "some other longer message here")],
    )
    assert extract_question(convo) == "Do you support X?"


def test_falls_back_to_first_substantive_user_message() -> None:
    convo = _convo(
        messages=[
            _msg("user", "hi"),
            _msg("assistant", "hello"),
            _msg("user", "What is your pricing model?"),
        ]
    )
    assert extract_question(convo) == "What is your pricing model?"


def test_none_when_no_question() -> None:
    assert extract_question(_convo(messages=[_msg("user", "ok")])) is None
    assert extract_question(_convo()) is None


def test_proposed_intent_is_deterministic_and_slugged() -> None:
    a = _proposed_intent("New Model Support")
    b = _proposed_intent("new   model   support")  # case/space-insensitive
    assert a == b and a.startswith("insight_")
    assert _proposed_intent("Different theme") != a
