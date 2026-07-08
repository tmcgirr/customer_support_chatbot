"""Test doubles for the model boundary.

Everything above the adapter is tested against ``FakeAdapter`` — the real OpenAI
SDK is never called in tests (CLAUDE.md: mock the adapter at its boundary).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.agent.adapter import (
    Completed,
    ModelMessage,
    StreamEvent,
    TextDelta,
    ToolSpec,
    Usage,
)


@dataclass
class _Call:
    instructions: str
    messages: list[ModelMessage]
    tools: list[ToolSpec] | None


class FakeAdapter:
    """Yields a scripted event sequence, optionally raising at the end.

    ``FakeAdapter.replying("some text")`` builds word-chunked TextDeltas plus a
    Completed. For failure paths, pass ``events`` (partial deltas, no Completed)
    and ``raises``.
    """

    def __init__(
        self,
        events: list[StreamEvent] | None = None,
        *,
        raises: Exception | None = None,
    ) -> None:
        self.events: list[StreamEvent] = events if events is not None else []
        self.raises = raises
        self.calls: list[_Call] = []

    @classmethod
    def replying(cls, text: str, *, usage: Usage | None = None) -> "FakeAdapter":
        words = text.split(" ")
        chunks = [w + " " for w in words[:-1]] + words[-1:] if words else []
        events: list[StreamEvent] = [TextDelta(text=c) for c in chunks]
        events.append(Completed(usage=usage or Usage(input_tokens=12, output_tokens=8)))
        return cls(events)

    async def send(
        self,
        *,
        instructions: str,
        messages: list[ModelMessage],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append(_Call(instructions=instructions, messages=list(messages), tools=tools))
        for event in self.events:
            yield event
        if self.raises is not None:
            raise self.raises
