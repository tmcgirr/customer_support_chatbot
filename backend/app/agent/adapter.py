"""Model provider boundary (CLAUDE.md invariant #4).

The OpenAI Responses API is called ONLY here. Nothing OpenAI-typed escapes this
module — the orchestrator sees normalized ``StreamEvent`` / ``Usage`` values and
``AdapterError``. Swapping providers is a change to this file alone.

Model calls are stateless: the orchestrator passes the system prompt
(``instructions``) plus the windowed transcript (``messages``) every turn. No
provider-side conversation object is created (ADR-014).
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI, OpenAIError

from app.core.config import get_settings
from app.core.errors import ErrorCode

# --- Normalized boundary types ------------------------------------------------


@dataclass(frozen=True)
class ModelMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class AssistantToolCall:
    """A function call the model made in a prior round, resent to continue the loop."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolOutput:
    """The application's result for a prior AssistantToolCall."""

    call_id: str
    output: str


# The stateless turn resends the whole conversation each round: prior text turns
# plus any tool call/result pairs from earlier rounds of the SAME turn.
InputItem = ModelMessage | AssistantToolCall | ToolOutput


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Completed:
    usage: Usage | None = None


StreamEvent = TextDelta | ToolCall | Completed


class AdapterError(Exception):
    """Any provider failure, normalized. Carries a client-safe error code."""

    def __init__(
        self, code: ErrorCode = ErrorCode.MODEL_UNAVAILABLE, message: str = "model unavailable"
    ) -> None:
        self.code = code
        super().__init__(message)


class ModelAdapter(Protocol):
    def send(
        self,
        *,
        instructions: str,
        messages: list[InputItem],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamEvent]: ...


# --- Helpers ------------------------------------------------------------------


def _to_input_item(item: InputItem) -> dict[str, Any]:
    if isinstance(item, ModelMessage):
        return {"role": item.role, "content": item.content}
    if isinstance(item, AssistantToolCall):
        return {
            "type": "function_call",
            "call_id": item.call_id,
            "name": item.name,
            "arguments": json.dumps(item.arguments),
        }
    return {"type": "function_call_output", "call_id": item.call_id, "output": item.output}


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _usage(response: Any) -> Usage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return Usage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


# --- OpenAI Responses adapter -------------------------------------------------


class OpenAIResponsesAdapter:
    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._client = client or AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        self._model = model or settings.openai_model

    async def send(
        self,
        *,
        instructions: str,
        messages: list[InputItem],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        request: dict[str, Any] = {
            "model": self._model,
            "instructions": instructions,
            "input": [_to_input_item(m) for m in messages],
            "stream": True,
            # Stateless: never persist the response provider-side (ADR-014 keeps
            # MongoDB the single store, so deletion is a one-store operation).
            "store": False,
        }
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in tools
            ]

        # Function-call arguments stream in pieces; accumulate per output item.
        # (Exercised in Phase 3 when read-only tools are registered.)
        tool_meta: dict[str, tuple[str, str]] = {}  # item_id -> (call_id, name)
        saw_completed = False

        try:
            stream: Any = await self._client.responses.create(**request)
            async for raw in stream:
                event: Any = raw
                etype = getattr(event, "type", "")
                # Refusals arrive as their own delta stream, not output_text.
                if etype in ("response.output_text.delta", "response.refusal.delta"):
                    yield TextDelta(text=event.delta)
                elif etype == "response.output_item.added":
                    item = event.item
                    if getattr(item, "type", "") == "function_call":
                        tool_meta[item.id] = (item.call_id, item.name)
                elif etype == "response.function_call_arguments.done":
                    call_id, name = tool_meta.get(event.item_id, ("", ""))
                    yield ToolCall(
                        call_id=call_id, name=name, arguments=_parse_arguments(event.arguments)
                    )
                elif etype == "response.completed":
                    saw_completed = True
                    yield Completed(usage=_usage(event.response))
                elif etype in ("response.failed", "response.incomplete", "error"):
                    raise AdapterError()
        # Catch the base type so no provider-typed exception ever escapes (#4);
        # `from None` so the provider message isn't chained onto the AdapterError.
        except OpenAIError:
            raise AdapterError() from None

        # A stream that ends without a terminal event (clean mid-stream EOF /
        # upstream truncation) is a failure, not a finished answer.
        if not saw_completed:
            raise AdapterError()

    async def aclose(self) -> None:
        await self._client.close()
