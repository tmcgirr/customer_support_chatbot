"""Adapter-level tests for the Anthropic Messages adapter: synthetic Anthropic SSE
events -> normalized StreamEvents. The real SDK is never called; a fake AsyncAnthropic
client feeds hand-built event objects through `send`."""

from types import SimpleNamespace
from typing import Any

import pytest
from anthropic import AnthropicError

from app.agent.adapter import (
    AdapterError,
    AnthropicMessagesAdapter,
    AssistantToolCall,
    Completed,
    ModelMessage,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolOutput,
    ToolSpec,
    _to_anthropic_messages,
)


def ev(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


class _FakeStream:
    def __init__(self, events: list[Any], stream_raise: Exception | None) -> None:
        self._events = events
        self._raise = stream_raise
        self.closed = False

    async def __aiter__(self) -> Any:
        for event in self._events:
            yield event
        if self._raise is not None:
            raise self._raise

    async def close(self) -> None:
        self.closed = True


class _FakeMessages:
    def __init__(
        self,
        events: list[Any],
        create_raise: Exception | None,
        stream_raise: Exception | None,
        message: Any,
    ) -> None:
        self._events = events
        self._create_raise = create_raise
        self._stream_raise = stream_raise
        self._message = message
        self.last_request: dict[str, Any] | None = None
        self.last_stream: _FakeStream | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_request = kwargs
        if self._create_raise is not None:
            raise self._create_raise
        if not kwargs.get("stream"):
            return self._message  # classify (non-streaming) path
        self.last_stream = _FakeStream(self._events, self._stream_raise)
        return self.last_stream


class _FakeClient:
    def __init__(
        self,
        events: list[Any] | None = None,
        *,
        create_raise: Exception | None = None,
        stream_raise: Exception | None = None,
        message: Any = None,
    ) -> None:
        self.messages = _FakeMessages(events or [], create_raise, stream_raise, message)

    async def close(self) -> None:
        pass


def _adapter(client: _FakeClient) -> AnthropicMessagesAdapter:
    return AnthropicMessagesAdapter(client=client, model="test-model")  # type: ignore[arg-type]


async def _collect(adapter: AnthropicMessagesAdapter) -> list[StreamEvent]:
    return [
        event
        async for event in adapter.send(
            instructions="sys", messages=[ModelMessage(role="user", content="hi")]
        )
    ]


async def test_streams_text_then_completed_with_usage() -> None:
    client = _FakeClient(
        [
            ev(type="message_start", message=ev(usage=ev(input_tokens=5))),
            ev(type="content_block_delta", index=0, delta=ev(type="text_delta", text="Hello")),
            ev(type="content_block_delta", index=0, delta=ev(type="text_delta", text=" world")),
            ev(type="content_block_stop", index=0),
            ev(type="message_delta", usage=ev(output_tokens=2)),
            ev(type="message_stop"),
        ]
    )
    events = await _collect(_adapter(client))

    assert [type(e).__name__ for e in events] == ["TextDelta", "TextDelta", "Completed"]
    assert isinstance(events[-1], Completed)
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 5
    assert events[-1].usage.output_tokens == 2
    assert events[-1].model == "test-model"
    # Anthropic requires max_tokens on every call (the per-response ceiling, L1).
    assert client.messages.last_request is not None
    assert client.messages.last_request["max_tokens"] > 0
    assert client.messages.last_request["stream"] is True
    assert client.messages.last_request["system"] == "sys"


async def test_tool_use_accumulates_name_and_arguments() -> None:
    client = _FakeClient(
        [
            ev(type="message_start", message=ev(usage=ev(input_tokens=3))),
            ev(
                type="content_block_start",
                index=0,
                content_block=ev(type="tool_use", id="toolu_1", name="search_knowledge"),
            ),
            ev(
                type="content_block_delta",
                index=0,
                delta=ev(type="input_json_delta", partial_json='{"query": '),
            ),
            ev(
                type="content_block_delta",
                index=0,
                delta=ev(type="input_json_delta", partial_json='"construction"}'),
            ),
            ev(type="content_block_stop", index=0),
            ev(type="message_delta", usage=ev(output_tokens=4)),
            ev(type="message_stop"),
        ]
    )
    events = await _collect(_adapter(client))
    tool_calls = [e for e in events if isinstance(e, ToolCall)]
    assert len(tool_calls) == 1
    assert tool_calls[0].call_id == "toolu_1"
    assert tool_calls[0].name == "search_knowledge"
    assert tool_calls[0].arguments == {"query": "construction"}


async def test_stream_without_message_stop_raises_adapter_error() -> None:
    # Deltas but no terminal message_stop -> failure, not a finished answer.
    client = _FakeClient(
        [ev(type="content_block_delta", index=0, delta=ev(type="text_delta", text="truncated"))]
    )
    with pytest.raises(AdapterError):
        await _collect(_adapter(client))


async def test_anthropic_error_on_create_maps_to_adapter_error() -> None:
    client = _FakeClient(create_raise=AnthropicError("boom"))
    with pytest.raises(AdapterError):
        await _collect(_adapter(client))


async def test_anthropic_error_mid_stream_maps_to_adapter_error() -> None:
    client = _FakeClient(
        [ev(type="content_block_delta", index=0, delta=ev(type="text_delta", text="x"))],
        stream_raise=AnthropicError("dropped"),
    )
    with pytest.raises(AdapterError):
        await _collect(_adapter(client))


async def test_stream_is_closed_after_run() -> None:
    client = _FakeClient(
        [
            ev(type="message_start", message=ev(usage=ev(input_tokens=1))),
            ev(type="content_block_delta", index=0, delta=ev(type="text_delta", text="ok")),
            ev(type="message_delta", usage=ev(output_tokens=1)),
            ev(type="message_stop"),
        ]
    )
    await _collect(_adapter(client))
    assert client.messages.last_stream is not None
    assert client.messages.last_stream.closed is True


async def test_request_maps_tools_and_message_transcript() -> None:
    client = _FakeClient(
        [
            ev(type="message_start", message=ev(usage=ev(input_tokens=1))),
            ev(type="message_delta", usage=ev(output_tokens=1)),
            ev(type="message_stop"),
        ]
    )
    adapter = _adapter(client)
    messages = [
        ModelMessage(role="user", content="hi"),
        AssistantToolCall(
            call_id="call_1", name="get_canonical_answer", arguments={"intent": "pricing"}
        ),
        ToolOutput(call_id="call_1", output='{"matched": true}'),
    ]
    tools = [ToolSpec(name="search_knowledge", description="d", parameters={"type": "object"})]
    _ = [event async for event in adapter.send(instructions="sys", messages=messages, tools=tools)]

    sent = client.messages.last_request
    assert sent is not None
    assert sent["tools"] == [
        {"name": "search_knowledge", "description": "d", "input_schema": {"type": "object"}}
    ]
    assert sent["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "get_canonical_answer",
                    "input": {"intent": "pricing"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": '{"matched": true}'}
            ],
        },
    ]


def test_to_anthropic_messages_coalesces_consecutive_same_role() -> None:
    folded = _to_anthropic_messages(
        [
            ModelMessage(role="user", content="one"),
            ModelMessage(role="user", content="two"),
        ]
    )
    assert folded == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "one"},
                {"type": "text", "text": "two"},
            ],
        }
    ]


async def test_classify_returns_concatenated_text_blocks() -> None:
    message = ev(content=[ev(type="text", text="lab"), ev(type="text", text="el")])
    client = _FakeClient(message=message)
    result = await _adapter(client).classify(instructions="sys", text="q")
    assert result == "label"
    assert client.messages.last_request is not None
    assert client.messages.last_request.get("stream") is not True


async def test_classify_error_maps_to_adapter_error() -> None:
    client = _FakeClient(create_raise=AnthropicError("boom"))
    with pytest.raises(AdapterError):
        await _adapter(client).classify(instructions="sys", text="q")


# --- Embeddings (delegated to OpenAI; Anthropic has none) --------------------


class _FakeEmbeddings:
    async def create(self, *, model: str, input: list[str]) -> Any:  # noqa: A002
        return ev(
            data=[ev(embedding=[0.1, 0.2]) for _ in input], usage=ev(prompt_tokens=len(input))
        )


class _FakeEmbedClient:
    def __init__(self) -> None:
        self.embeddings = _FakeEmbeddings()

    async def close(self) -> None:
        pass


async def test_embed_delegates_to_openai_client() -> None:
    adapter = AnthropicMessagesAdapter(
        client=_FakeClient(),  # type: ignore[arg-type]
        model="test-model",
        embed_client=_FakeEmbedClient(),  # type: ignore[arg-type]
    )
    vectors = await adapter.embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.1, 0.2]]


async def test_embed_fails_closed_when_no_openai_key() -> None:
    adapter = _adapter(_FakeClient())
    adapter._embed_client = None  # simulate no OpenAI key configured
    with pytest.raises(AdapterError):
        await adapter.embed(["a"])


# --- Usage recording (the on_usage hook feeds the llm_usage rollup) ----------


async def test_classify_records_usage_via_on_usage() -> None:
    recorded: list[tuple[str, str, int, int]] = []

    async def rec(model: str, category: str, inp: int, out: int) -> None:
        recorded.append((model, category, inp, out))

    message = ev(usage=ev(input_tokens=7, output_tokens=3), content=[ev(type="text", text="ok")])
    adapter = AnthropicMessagesAdapter(
        client=_FakeClient(message=message),  # type: ignore[arg-type]
        model="test-model",
        on_usage=rec,
    )
    await adapter.classify(instructions="s", text="q", category="labeling")
    assert recorded == [("test-model", "labeling", 7, 3)]


async def test_embed_records_usage_via_on_usage() -> None:
    from app.core.config import get_settings

    recorded: list[tuple[str, str, int, int]] = []

    async def rec(model: str, category: str, inp: int, out: int) -> None:
        recorded.append((model, category, inp, out))

    adapter = AnthropicMessagesAdapter(
        client=_FakeClient(),  # type: ignore[arg-type]
        model="test-model",
        embed_client=_FakeEmbedClient(),  # type: ignore[arg-type]
        on_usage=rec,
    )
    await adapter.embed(["a", "b"], category="embeddings")
    # Embeddings bill input (prompt) tokens only, attributed to the OpenAI embed model.
    assert recorded == [(get_settings().insights_embed_model, "embeddings", 2, 0)]


# --- Fallback (mirrors the OpenAI adapter's fallback semantics) --------------


class _PerModelMessages:
    def __init__(self, behaviors: dict[str, tuple[Any, ...]]) -> None:
        self._behaviors = behaviors
        self.models_called: list[str] = []

    async def create(self, **kwargs: Any) -> _FakeStream:
        model = kwargs["model"]
        self.models_called.append(model)
        events, create_raise = self._behaviors[model][0], self._behaviors[model][1]
        if create_raise is not None:
            raise create_raise
        return _FakeStream(events, None)


class _PerModelClient:
    def __init__(self, behaviors: dict[str, tuple[Any, ...]]) -> None:
        self.messages = _PerModelMessages(behaviors)

    async def close(self) -> None:
        pass


async def test_falls_back_to_fallback_model_on_early_failure() -> None:
    client = _PerModelClient(
        {
            "primary": ([], AnthropicError("down")),
            "backup": (
                [
                    ev(type="message_start", message=ev(usage=ev(input_tokens=1))),
                    ev(
                        type="content_block_delta",
                        index=0,
                        delta=ev(type="text_delta", text="hi from backup"),
                    ),
                    ev(type="message_delta", usage=ev(output_tokens=1)),
                    ev(type="message_stop"),
                ],
                None,
            ),
        }
    )
    adapter = AnthropicMessagesAdapter(client=client, model="primary", fallback_model="backup")  # type: ignore[arg-type]
    events = [
        e
        async for e in adapter.send(
            instructions="s", messages=[ModelMessage(role="user", content="x")]
        )
    ]
    texts = "".join(e.text for e in events if isinstance(e, TextDelta))
    completed = [e for e in events if isinstance(e, Completed)]
    assert texts == "hi from backup"
    assert completed[-1].model == "backup"
    assert client.messages.models_called == ["primary", "backup"]


async def test_midstream_failure_is_not_retried_on_fallback() -> None:
    client = _PerModelClient(
        {
            "primary": (
                [ev(type="content_block_delta", index=0, delta=ev(type="text_delta", text="p"))],
                None,
            ),
            "backup": ([ev(type="message_stop")], None),
        }
    )
    adapter = AnthropicMessagesAdapter(client=client, model="primary", fallback_model="backup")  # type: ignore[arg-type]
    collected: list[StreamEvent] = []
    with pytest.raises(AdapterError):
        async for e in adapter.send(instructions="s", messages=[]):
            collected.append(e)
    assert "".join(e.text for e in collected if isinstance(e, TextDelta)) == "p"
    assert "backup" not in client.messages.models_called
