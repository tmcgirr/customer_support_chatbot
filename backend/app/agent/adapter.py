"""Model provider boundary (CLAUDE.md invariant #4).

The provider APIs (OpenAI Responses, Anthropic Messages) are called ONLY here.
Nothing provider-typed escapes this module — the orchestrator sees normalized
``StreamEvent`` / ``Usage`` values and ``AdapterError``. Adding or swapping a
provider is a change to this file alone; which provider is active is resolved
outside (config default + the admin runtime toggle) and passed as a built adapter.

Model calls are stateless: the orchestrator passes the system prompt
(``instructions``) plus the windowed transcript (``messages``) every turn. No
provider-side conversation object is created (ADR-014).
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from anthropic import AnthropicError, AsyncAnthropic
from openai import AsyncOpenAI, OpenAIError

from app.core.config import get_settings
from app.core.errors import ErrorCode
from app.core.logging import get_logger

logger = get_logger("app.adapter")

# Optional usage sink for the non-streaming paths (classify/embed): (model, category,
# input_tokens, output_tokens). The wiring layer provides an implementation that writes to
# the llm_usage rollup; the adapter stays free of persistence types (invariant #4).
UsageHook = Callable[[str, str, int, int], Awaitable[None]]

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
    model: str | None = None  # the model that actually produced the answer (may be the fallback)


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

    async def classify(self, *, instructions: str, text: str, category: str = "classify") -> str:
        """One-shot, non-streaming, tool-less completion for offline classification
        (e.g. analytics labeling). Returns the model's raw text; the caller validates
        it. Read-only — no tools, never persisted provider-side. ``category`` labels the
        usage rollup row (labeling / summary / insights)."""
        ...

    async def embed(self, texts: list[str], *, category: str = "embeddings") -> list[list[float]]:
        """Batch-embed texts for offline clustering (conversation insights). Returns one
        vector per input, in order. Read-only; provider errors are normalized. ``category``
        labels the usage rollup row."""
        ...


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
    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
        on_usage: UsageHook | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        embed_client: AsyncOpenAI | None = None,
    ) -> None:
        """``base_url`` points the CHAT client at an OpenAI-Responses-compatible proxy
        (e.g. OpenRouter) — the same adapter, a different host and (non-native) model id.
        Embeddings ALWAYS go to real OpenAI: when the chat client is a proxy, a dedicated
        OpenAI ``embed_client`` is built from the OpenAI key; otherwise the chat client
        already IS OpenAI, so it is reused. All OpenAI types stay inside this module (#4)."""
        settings = get_settings()
        key = api_key if api_key is not None else settings.openai_api_key.get_secret_value()
        if client is not None:
            self._client = client
        elif base_url:
            self._client = AsyncOpenAI(api_key=key, base_url=base_url)
        else:
            self._client = AsyncOpenAI(api_key=key)
        self._model = model or settings.openai_model
        self._fallback_model = (
            fallback_model if fallback_model is not None else settings.openai_fallback_model
        )
        self._embed_model = settings.insights_embed_model
        # Hard per-response output ceiling on every call (SECURITY_REVIEW_V1 L1).
        self._max_output_tokens = settings.openai_max_output_tokens
        # Optional usage sink for classify/embed (chat usage is recorded elsewhere).
        self._on_usage = on_usage
        # Embeddings never go through a proxy. With a proxy chat client, use a dedicated real
        # OpenAI client (fails closed to None if no OpenAI key); otherwise reuse the chat client.
        if embed_client is not None:
            self._embed_client: AsyncOpenAI | None = embed_client
        elif base_url:
            openai_key = settings.openai_api_key.get_secret_value()
            self._embed_client = AsyncOpenAI(api_key=openai_key) if openai_key else None
        else:
            self._embed_client = self._client

    async def send(
        self,
        *,
        instructions: str,
        messages: list[InputItem],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream the primary model; if it fails BEFORE any output streams and a
        fallback is configured, retry once on the fallback. A mid-stream failure
        (after deltas were yielded) is NOT retried — it would duplicate output."""
        started = False
        try:
            async for event in self._stream(self._model, instructions, messages, tools):
                started = True
                yield event
            return
        except AdapterError as exc:
            # Only retry a MODEL_UNAVAILABLE that failed before any output streamed
            # (retrying mid-stream would duplicate output; retrying a non-model
            # error would just fail again on the fallback).
            if started or exc.code != ErrorCode.MODEL_UNAVAILABLE or not self._fallback_model:
                raise
            logger.info("model.fallback", extra={"context": {"model": self._fallback_model}})
        async for event in self._stream(self._fallback_model, instructions, messages, tools):
            yield event

    async def _stream(
        self,
        model: str,
        instructions: str,
        messages: list[InputItem],
        tools: list[ToolSpec] | None,
    ) -> AsyncIterator[StreamEvent]:
        request: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": [_to_input_item(m) for m in messages],
            "stream": True,
            # Stateless: never persist the response provider-side (ADR-014 keeps
            # MongoDB the single store, so deletion is a one-store operation).
            "store": False,
            # Bound a single response's length (cost / lock-hold; SECURITY_REVIEW_V1 L1).
            "max_output_tokens": self._max_output_tokens,
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
        except OpenAIError:
            raise AdapterError() from None

        try:
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
                    yield Completed(usage=_usage(event.response), model=model)
                elif etype in ("response.failed", "response.incomplete", "error"):
                    raise AdapterError()
        # Catch the base type so no provider-typed exception ever escapes (#4);
        # `from None` so the provider message isn't chained onto the AdapterError.
        except OpenAIError:
            raise AdapterError() from None
        finally:
            # Release the HTTP stream deterministically on completion, error, or an
            # early consumer stop (client disconnect → GeneratorExit at a yield).
            closer = getattr(stream, "close", None)
            if closer is not None:
                await closer()

        # A stream that ends without a terminal event (clean mid-stream EOF /
        # upstream truncation) is a failure, not a finished answer.
        if not saw_completed:
            raise AdapterError()

    async def classify(self, *, instructions: str, text: str, category: str = "classify") -> str:
        """Non-streaming single completion. Provider errors are normalized to
        AdapterError so no OpenAI type escapes (invariant #4). No tools, ``store=False``."""
        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=instructions,
                input=text,
                stream=False,
                store=False,
                max_output_tokens=self._max_output_tokens,
            )
        except Exception:  # normalize every provider failure at the boundary
            # `from None` severs the provider exception (matches send()/_stream()): no
            # OpenAI-typed object is retained on __cause__ (invariant #4).
            raise AdapterError() from None
        usage = _usage(response)
        if usage is not None and self._on_usage is not None:
            await self._on_usage(self._model, category, usage.input_tokens, usage.output_tokens)
        return str(getattr(response, "output_text", "") or "")

    async def embed(self, texts: list[str], *, category: str = "embeddings") -> list[list[float]]:
        """Batch embeddings for offline clustering. One provider call for the whole batch;
        errors normalized to AdapterError so no OpenAI type escapes (invariant #4)."""
        if not texts:
            return []
        if self._embed_client is None:
            raise AdapterError()
        try:
            response = await self._embed_client.embeddings.create(
                model=self._embed_model, input=texts
            )
        except Exception:
            raise AdapterError() from None
        if self._on_usage is not None:
            # Embeddings bill input (prompt) tokens only — there is no output.
            prompt_tokens = int(getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0)
            await self._on_usage(self._embed_model, category, prompt_tokens, 0)
        return [list(item.embedding) for item in response.data]

    async def aclose(self) -> None:
        await self._client.close()
        # Close the dedicated embed client too, unless it is the same object as the chat client.
        if self._embed_client is not None and self._embed_client is not self._client:
            await self._embed_client.close()


# --- Anthropic Messages adapter ----------------------------------------------


def _to_anthropic_messages(items: list[InputItem]) -> list[dict[str, Any]]:
    """Fold the flat, provider-neutral turn transcript into Anthropic's message +
    content-block shape. Consecutive same-role items coalesce into one message so
    tool_use (assistant) / tool_result (user) blocks are grouped correctly."""
    messages: list[dict[str, Any]] = []
    role: str
    block: dict[str, Any]
    for item in items:
        if isinstance(item, ModelMessage):
            role = item.role
            block = {"type": "text", "text": item.content}
        elif isinstance(item, AssistantToolCall):
            role = "assistant"
            block = {
                "type": "tool_use",
                "id": item.call_id,
                "name": item.name,
                "input": item.arguments,
            }
        else:  # ToolOutput
            role = "user"
            block = {"type": "tool_result", "tool_use_id": item.call_id, "content": item.output}
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].append(block)
        else:
            messages.append({"role": role, "content": [block]})
    return messages


class AnthropicMessagesAdapter:
    """Claude via the Anthropic Messages API. Structurally mirrors the OpenAI adapter:
    same fallback-before-first-output retry, same deterministic stream close, and every
    Anthropic error/type normalized at this boundary (invariant #4).

    Thinking is left OFF (the ``thinking`` param is omitted) — the support turn wants
    concise, tool-driven answers under a shared output-token cap, not extended reasoning.

    Anthropic has no embeddings endpoint, so ``embed`` (insights clustering) is served
    by an internal OpenAI embeddings client; an OpenAI key stays required for that path.
    """

    def __init__(
        self,
        client: AsyncAnthropic | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
        embed_client: AsyncOpenAI | None = None,
        on_usage: UsageHook | None = None,
    ) -> None:
        settings = get_settings()
        self._client = client or AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._model = model or settings.anthropic_model
        self._fallback_model = (
            fallback_model if fallback_model is not None else settings.anthropic_fallback_model
        )
        self._max_output_tokens = settings.anthropic_max_output_tokens
        # Optional usage sink for classify/embed (chat usage is recorded elsewhere).
        self._on_usage = on_usage
        # Embeddings have no Anthropic equivalent — reuse OpenAI. Built lazily-ish here so
        # it is absent (and embed() fails closed) when no OpenAI key is configured.
        self._embed_model = settings.insights_embed_model
        openai_key = settings.openai_api_key.get_secret_value()
        self._embed_client = embed_client or (
            AsyncOpenAI(api_key=openai_key) if openai_key else None
        )

    async def send(
        self,
        *,
        instructions: str,
        messages: list[InputItem],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream the primary model; retry once on the fallback ONLY if the primary
        failed before any output streamed (mirrors the OpenAI adapter — a mid-stream
        failure is never retried, a non-model error would just fail again)."""
        started = False
        try:
            async for event in self._stream(self._model, instructions, messages, tools):
                started = True
                yield event
            return
        except AdapterError as exc:
            if started or exc.code != ErrorCode.MODEL_UNAVAILABLE or not self._fallback_model:
                raise
            logger.info("model.fallback", extra={"context": {"model": self._fallback_model}})
        async for event in self._stream(self._fallback_model, instructions, messages, tools):
            yield event

    async def _stream(
        self,
        model: str,
        instructions: str,
        messages: list[InputItem],
        tools: list[ToolSpec] | None,
    ) -> AsyncIterator[StreamEvent]:
        request: dict[str, Any] = {
            "model": model,
            "system": instructions,
            "messages": _to_anthropic_messages(messages),
            "max_tokens": self._max_output_tokens,
            "stream": True,
        }
        if tools:
            request["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]

        # Function-call arguments stream as partial JSON per content block; accumulate.
        tool_meta: dict[int, tuple[str, str]] = {}  # block index -> (call_id, name)
        tool_json: dict[int, list[str]] = {}  # block index -> partial_json parts
        input_tokens = 0
        output_tokens = 0
        saw_completed = False

        try:
            stream: Any = await self._client.messages.create(**request)
        except AnthropicError:
            raise AdapterError() from None

        try:
            async for raw in stream:
                event: Any = raw
                etype = getattr(event, "type", "")
                if etype == "message_start":
                    usage = getattr(event.message, "usage", None)
                    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                elif etype == "content_block_start":
                    block = event.content_block
                    if getattr(block, "type", "") == "tool_use":
                        tool_meta[event.index] = (block.id, block.name)
                        tool_json[event.index] = []
                elif etype == "content_block_delta":
                    delta = event.delta
                    dtype = getattr(delta, "type", "")
                    if dtype == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield TextDelta(text=text)
                    elif dtype == "input_json_delta":
                        tool_json.setdefault(event.index, []).append(delta.partial_json)
                elif etype == "content_block_stop":
                    meta = tool_meta.pop(event.index, None)
                    if meta is not None:
                        call_id, name = meta
                        raw_args = "".join(tool_json.pop(event.index, []))
                        yield ToolCall(
                            call_id=call_id, name=name, arguments=_parse_arguments(raw_args)
                        )
                elif etype == "message_delta":
                    usage = getattr(event, "usage", None)
                    if usage is not None:
                        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                elif etype == "message_stop":
                    saw_completed = True
                    yield Completed(
                        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                        model=model,
                    )
        # Catch the base type so no Anthropic-typed exception ever escapes (#4).
        except AnthropicError:
            raise AdapterError() from None
        finally:
            closer = getattr(stream, "close", None)
            if closer is not None:
                await closer()

        # A stream that ends without a terminal event is a failure, not a finished answer.
        if not saw_completed:
            raise AdapterError()

    async def classify(self, *, instructions: str, text: str, category: str = "classify") -> str:
        """Non-streaming single completion. Provider errors normalized to AdapterError so
        no Anthropic type escapes (invariant #4). No tools."""
        try:
            response = await self._client.messages.create(
                model=self._model,
                system=instructions,
                messages=[{"role": "user", "content": text}],
                max_tokens=self._max_output_tokens,
            )
        except Exception:
            raise AdapterError() from None
        usage = _usage(response)
        if usage is not None and self._on_usage is not None:
            await self._on_usage(self._model, category, usage.input_tokens, usage.output_tokens)
        parts = [
            getattr(block, "text", "")
            for block in getattr(response, "content", [])
            if getattr(block, "type", "") == "text"
        ]
        return "".join(parts)

    async def embed(self, texts: list[str], *, category: str = "embeddings") -> list[list[float]]:
        """Batch embeddings for offline clustering — delegated to OpenAI (Anthropic has no
        embeddings API). Fails closed (AdapterError) when no OpenAI key is configured. Usage is
        attributed to the OpenAI embedding model regardless of the active chat provider."""
        if not texts:
            return []
        if self._embed_client is None:
            raise AdapterError()
        try:
            response = await self._embed_client.embeddings.create(
                model=self._embed_model, input=texts
            )
        except Exception:
            raise AdapterError() from None
        if self._on_usage is not None:
            prompt_tokens = int(getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0)
            await self._on_usage(self._embed_model, category, prompt_tokens, 0)
        return [list(item.embedding) for item in response.data]

    async def aclose(self) -> None:
        await self._client.close()
        if self._embed_client is not None:
            await self._embed_client.close()
