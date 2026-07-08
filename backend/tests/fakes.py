"""Test doubles for the model + retrieval boundaries.

Everything above the adapter is tested against these — the real OpenAI SDK is
never called in tests (CLAUDE.md: mock at the boundary).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.agent.adapter import (
    Completed,
    InputItem,
    StreamEvent,
    TextDelta,
    ToolSpec,
    Usage,
)
from app.domain.knowledge.search import SearchResult


@dataclass
class _Call:
    instructions: str
    messages: list[InputItem]
    tools: list[ToolSpec] | None


class FakeAdapter:
    """Yields a scripted event sequence.

    - ``FakeAdapter.replying("text")`` → one round of word-chunked deltas + Completed.
    - ``FakeAdapter.with_rounds([[...], [...]])`` → the i-th send() yields the i-th
      round's events (for exercising the multi-round tool loop).
    - ``events`` + ``raises`` → single round with an optional trailing exception.
    """

    def __init__(
        self,
        events: list[StreamEvent] | None = None,
        *,
        raises: Exception | None = None,
        rounds: list[list[StreamEvent]] | None = None,
    ) -> None:
        self.events: list[StreamEvent] = events if events is not None else []
        self.raises = raises
        self._rounds = rounds
        self._round_index = 0
        self.calls: list[_Call] = []

    @classmethod
    def replying(cls, text: str, *, usage: Usage | None = None) -> "FakeAdapter":
        words = text.split(" ")
        chunks = [w + " " for w in words[:-1]] + words[-1:] if words else []
        events: list[StreamEvent] = [TextDelta(text=c) for c in chunks]
        events.append(Completed(usage=usage or Usage(input_tokens=12, output_tokens=8)))
        return cls(events)

    @classmethod
    def with_rounds(cls, rounds: list[list[StreamEvent]]) -> "FakeAdapter":
        return cls(rounds=rounds)

    def set_rounds(self, rounds: list[list[StreamEvent]]) -> None:
        self._rounds = rounds
        self._round_index = 0

    async def send(
        self,
        *,
        instructions: str,
        messages: list[InputItem],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append(_Call(instructions=instructions, messages=list(messages), tools=tools))
        if self._rounds is not None:
            index = min(self._round_index, len(self._rounds) - 1)
            self._round_index += 1
            for event in self._rounds[index]:
                yield event
            return
        for event in self.events:
            yield event
        if self.raises is not None:
            raise self.raises


class FakeKnowledgeSearch:
    """Returns a canned SearchResult; records queries. Never calls a provider."""

    def __init__(self, result: SearchResult | None = None) -> None:
        self.result = result if result is not None else SearchResult("empty", [])
        self.calls: list[tuple[str, list[str] | None, int]] = []

    async def search(
        self, query: str, *, categories: list[str] | None = None, max_results: int = 5
    ) -> SearchResult:
        self.calls.append((query, categories, max_results))
        return self.result

    async def aclose(self) -> None:
        pass
