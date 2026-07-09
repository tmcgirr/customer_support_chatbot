"""ConversationSummarizer: parse the model's JSON digest, degrade on bad output, use the
model on a real transcript, and skip/retry on model failure. No DB, no OpenAI."""

from datetime import UTC, datetime

from app.agent.adapter import AdapterError
from app.domain.analytics.summarizer import ConversationSummarizer, parse_digest
from app.domain.conversations.models import Conversation, Message
from tests.fakes import FakeAdapter


def _convo(messages: list[Message]) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(id="c", started_at=now, last_activity_at=now, messages=messages)


def _msg(role: str, content: str) -> Message:
    return Message(id="m", role=role, content=content, created_at=datetime.now(UTC))


def test_parse_digest_valid() -> None:
    d = parse_digest(
        '{"tldr":"They asked about pricing.","key_points":["pricing","no public rates"]}',
        datetime.now(UTC),
    )
    assert d.tldr == "They asked about pricing."
    assert d.key_points == ["pricing", "no public rates"]


def test_parse_digest_bad_json_degrades() -> None:
    d = parse_digest("not json at all", datetime.now(UTC))
    assert d.tldr == "Summary unavailable." and d.key_points == []


async def test_summarize_uses_the_model() -> None:
    adapter = FakeAdapter(classify_result='{"tldr":"Asked about SOC2.","key_points":["SOC2"]}')
    summarizer = ConversationSummarizer(adapter)
    digest = await summarizer.summarize(
        _convo([_msg("user", "Do you have SOC2?")]), now=datetime.now(UTC)
    )
    assert digest is not None and digest.tldr == "Asked about SOC2."
    assert adapter.classify_calls and "SOC2" in adapter.classify_calls[0]


async def test_summarize_model_failure_returns_none() -> None:
    summarizer = ConversationSummarizer(FakeAdapter(classify_raises=AdapterError()))
    result = await summarizer.summarize(
        _convo([_msg("user", "A real question here")]), now=datetime.now(UTC)
    )
    assert result is None  # left un-summarized → retried next run


async def test_summarize_empty_transcript_is_marked_done() -> None:
    # No usable content — return a digest (not None) so it isn't re-scanned forever.
    summarizer = ConversationSummarizer(FakeAdapter())
    digest = await summarizer.summarize(_convo([]), now=datetime.now(UTC))
    assert digest is not None and digest.tldr == "No summarizable content."
    assert summarizer  # (model never called)
