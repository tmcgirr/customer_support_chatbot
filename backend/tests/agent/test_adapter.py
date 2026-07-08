"""Adapter-level tests: synthetic OpenAI events -> normalized StreamEvents.

This is the riskiest, most provider-coupled code; the real SDK is never called.
A fake AsyncOpenAI client feeds hand-built event objects through `send`.
"""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError

from app.agent.adapter import (
    AdapterError,
    AssistantToolCall,
    Completed,
    ModelMessage,
    OpenAIResponsesAdapter,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolOutput,
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


class _FakeResponses:
    def __init__(
        self, events: list[Any], create_raise: Exception | None, stream_raise: Exception | None
    ) -> None:
        self._events = events
        self._create_raise = create_raise
        self._stream_raise = stream_raise
        self.last_request: dict[str, Any] | None = None
        self.last_stream: _FakeStream | None = None

    async def create(self, **kwargs: Any) -> _FakeStream:
        self.last_request = kwargs
        if self._create_raise is not None:
            raise self._create_raise
        self.last_stream = _FakeStream(self._events, self._stream_raise)
        return self.last_stream


class _FakeClient:
    def __init__(
        self,
        events: list[Any] | None = None,
        *,
        create_raise: Exception | None = None,
        stream_raise: Exception | None = None,
    ) -> None:
        self.responses = _FakeResponses(events or [], create_raise, stream_raise)

    async def close(self) -> None:
        pass


def _adapter(client: _FakeClient) -> OpenAIResponsesAdapter:
    return OpenAIResponsesAdapter(client=client, model="test-model")  # type: ignore[arg-type]


async def _collect(adapter: OpenAIResponsesAdapter) -> list[StreamEvent]:
    return [
        event
        async for event in adapter.send(
            instructions="sys", messages=[ModelMessage(role="user", content="hi")]
        )
    ]


async def test_streams_text_then_completed_with_usage() -> None:
    client = _FakeClient(
        [
            ev(type="response.output_text.delta", delta="Hello"),
            ev(type="response.output_text.delta", delta=" world"),
            ev(type="response.completed", response=ev(usage=ev(input_tokens=5, output_tokens=2))),
        ]
    )
    adapter = _adapter(client)
    events = await _collect(adapter)

    assert [type(e).__name__ for e in events] == ["TextDelta", "TextDelta", "Completed"]
    assert isinstance(events[-1], Completed)
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 5
    # Stateless: store must be disabled.
    assert client.responses.last_request is not None
    assert client.responses.last_request["store"] is False


async def test_refusal_delta_is_surfaced_as_text() -> None:
    client = _FakeClient(
        [
            ev(type="response.refusal.delta", delta="I can't help with that."),
            ev(type="response.completed", response=ev(usage=None)),
        ]
    )
    events = await _collect(_adapter(client))
    assert isinstance(events[0], TextDelta)
    assert events[0].text == "I can't help with that."


async def test_tool_call_accumulates_name_and_arguments() -> None:
    client = _FakeClient(
        [
            ev(
                type="response.output_item.added",
                item=ev(type="function_call", id="fc_1", call_id="call_1", name="search_knowledge"),
            ),
            ev(
                type="response.function_call_arguments.done",
                item_id="fc_1",
                arguments='{"query": "construction"}',
            ),
            ev(type="response.completed", response=ev(usage=None)),
        ]
    )
    events = await _collect(_adapter(client))
    tool_calls = [e for e in events if isinstance(e, ToolCall)]
    assert len(tool_calls) == 1
    assert tool_calls[0].call_id == "call_1"
    assert tool_calls[0].name == "search_knowledge"
    assert tool_calls[0].arguments == {"query": "construction"}


async def test_response_failed_event_raises_adapter_error() -> None:
    client = _FakeClient(
        [ev(type="response.output_text.delta", delta="partial"), ev(type="response.failed")]
    )
    with pytest.raises(AdapterError):
        await _collect(_adapter(client))


async def test_stream_without_completed_raises_adapter_error() -> None:
    # Clean mid-stream EOF: deltas but no terminal event -> failure, not success.
    client = _FakeClient([ev(type="response.output_text.delta", delta="truncated")])
    with pytest.raises(AdapterError):
        await _collect(_adapter(client))


async def test_openai_error_on_create_maps_to_adapter_error() -> None:
    client = _FakeClient(create_raise=OpenAIError("boom"))
    with pytest.raises(AdapterError):
        await _collect(_adapter(client))


async def test_openai_error_mid_stream_maps_to_adapter_error() -> None:
    client = _FakeClient(
        [ev(type="response.output_text.delta", delta="x")], stream_raise=OpenAIError("dropped")
    )
    with pytest.raises(AdapterError):
        await _collect(_adapter(client))


async def test_tool_call_input_items_serialize_for_round_two() -> None:
    # The round-2 input (function_call + function_call_output) is what makes the
    # multi-round tool loop work against the real Responses API.
    client = _FakeClient([ev(type="response.completed", response=ev(usage=None))])
    adapter = _adapter(client)
    messages = [
        ModelMessage(role="user", content="hi"),
        AssistantToolCall(
            call_id="call_1", name="get_canonical_answer", arguments={"intent": "pricing"}
        ),
        ToolOutput(call_id="call_1", output='{"matched": true}'),
    ]
    _ = [event async for event in adapter.send(instructions="sys", messages=messages)]

    sent = client.responses.last_request
    assert sent is not None
    items = sent["input"]
    assert items[0] == {"role": "user", "content": "hi"}
    assert items[1]["type"] == "function_call"
    assert items[1]["call_id"] == "call_1"
    assert items[1]["name"] == "get_canonical_answer"
    assert json.loads(items[1]["arguments"]) == {"intent": "pricing"}  # arguments is a JSON string
    assert items[2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"matched": true}',
    }


# --- Model fallback ----------------------------------------------------------


class _PerModelResponses:
    """create() behaves per model. Behavior tuple: (events, create_raise[, stream_raise])."""

    def __init__(self, behaviors: dict[str, tuple[Any, ...]]) -> None:
        self._behaviors = behaviors
        self.models_called: list[str] = []

    async def create(self, **kwargs: Any) -> _FakeStream:
        model = kwargs["model"]
        self.models_called.append(model)
        behavior = self._behaviors[model]
        events, create_raise = behavior[0], behavior[1]
        stream_raise = behavior[2] if len(behavior) > 2 else None
        if create_raise is not None:
            raise create_raise
        return _FakeStream(events, stream_raise)


class _PerModelClient:
    def __init__(self, behaviors: dict[str, tuple[Any, ...]]) -> None:
        self.responses = _PerModelResponses(behaviors)

    async def close(self) -> None:
        pass


async def test_falls_back_to_fallback_model_on_early_failure() -> None:
    client = _PerModelClient(
        {
            "primary": ([], OpenAIError("down")),  # create fails before any output
            "backup": (
                [
                    ev(type="response.output_text.delta", delta="hi from backup"),
                    ev(type="response.completed", response=ev(usage=None)),
                ],
                None,
            ),
        }
    )
    adapter = OpenAIResponsesAdapter(client=client, model="primary", fallback_model="backup")  # type: ignore[arg-type]
    events = [
        e
        async for e in adapter.send(
            instructions="s", messages=[ModelMessage(role="user", content="x")]
        )
    ]
    texts = "".join(e.text for e in events if isinstance(e, TextDelta))
    completed = [e for e in events if isinstance(e, Completed)]
    assert texts == "hi from backup"
    assert completed[-1].model == "backup"  # the answer reports the fallback model
    assert client.responses.models_called == ["primary", "backup"]


async def test_no_fallback_configured_raises_and_does_not_retry() -> None:
    client = _PerModelClient({"primary": ([], OpenAIError("down"))})
    adapter = OpenAIResponsesAdapter(client=client, model="primary", fallback_model="")  # type: ignore[arg-type]
    with pytest.raises(AdapterError):
        [e async for e in adapter.send(instructions="s", messages=[])]
    assert client.responses.models_called == ["primary"]  # no fallback attempted


async def test_midstream_failure_is_not_retried_on_fallback() -> None:
    # primary yields a delta then ends without a terminal event (AdapterError):
    # output already started, so the fallback must NOT be tried (no dup output).
    client = _PerModelClient(
        {
            "primary": ([ev(type="response.output_text.delta", delta="partial")], None),
            "backup": ([ev(type="response.completed", response=ev(usage=None))], None),
        }
    )
    adapter = OpenAIResponsesAdapter(client=client, model="primary", fallback_model="backup")  # type: ignore[arg-type]
    collected: list[StreamEvent] = []
    with pytest.raises(AdapterError):
        async for e in adapter.send(instructions="s", messages=[]):
            collected.append(e)
    assert "".join(e.text for e in collected if isinstance(e, TextDelta)) == "partial"
    assert "backup" not in client.responses.models_called


async def test_completed_reports_primary_model_when_no_fallback_needed() -> None:
    client = _FakeClient(
        [
            ev(type="response.output_text.delta", delta="ok"),
            ev(type="response.completed", response=ev(usage=None)),
        ]
    )
    adapter = OpenAIResponsesAdapter(client=client, model="primary-m", fallback_model="backup")  # type: ignore[arg-type]
    events = await _collect(adapter)
    completed = [e for e in events if isinstance(e, Completed)]
    assert completed[-1].model == "primary-m"


async def test_midstream_openai_error_with_fallback_is_not_retried() -> None:
    # The realistic mid-stream failure: a delta streams, THEN the provider drops
    # with an OpenAIError. Output already started -> the fallback must NOT run.
    client = _PerModelClient(
        {
            "primary": (
                [ev(type="response.output_text.delta", delta="partial")],
                None,
                OpenAIError("dropped"),
            ),
            "backup": ([ev(type="response.completed", response=ev(usage=None))], None, None),
        }
    )
    adapter = OpenAIResponsesAdapter(client=client, model="primary", fallback_model="backup")  # type: ignore[arg-type]
    collected: list[StreamEvent] = []
    with pytest.raises(AdapterError):
        async for e in adapter.send(instructions="s", messages=[]):
            collected.append(e)
    assert "".join(e.text for e in collected if isinstance(e, TextDelta)) == "partial"
    assert "backup" not in client.responses.models_called


async def test_non_model_adapter_error_is_not_retried_on_fallback() -> None:
    # Fallback is only for MODEL_UNAVAILABLE; a different code must propagate as-is.
    from app.core.errors import ErrorCode

    class _RetrievalFail:
        def __init__(self) -> None:
            self.models_called: list[str] = []

        async def create(self, **kwargs: Any) -> _FakeStream:
            self.models_called.append(kwargs["model"])
            raise AdapterError(ErrorCode.RETRIEVAL_UNAVAILABLE)

    responses = _RetrievalFail()
    client = SimpleNamespace(responses=responses)
    adapter = OpenAIResponsesAdapter(client=client, model="primary", fallback_model="backup")  # type: ignore[arg-type]
    with pytest.raises(AdapterError):
        [e async for e in adapter.send(instructions="s", messages=[])]
    assert responses.models_called == ["primary"]  # no fallback for a non-model error


async def test_stream_is_closed_after_run() -> None:
    client = _FakeClient(
        [
            ev(type="response.output_text.delta", delta="ok"),
            ev(type="response.completed", response=ev(usage=None)),
        ]
    )
    await _collect(_adapter(client))
    assert client.responses.last_stream is not None
    assert client.responses.last_stream.closed is True
