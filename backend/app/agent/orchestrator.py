"""Chat orchestrator — the turn loop with read-only tools (ADR §3.1, ADR-016).

begin_turn (atomic lock+append) → build the window → run the model/tool loop
(the model may call the read-only tools; the app executes them and resends the
transcript each round, stateless) → complete_turn / fail_turn, persisting the
assistant message with content, usage, latency, canonical_answer_id, sources,
suggested actions, and any error_code.

The orchestrator yields transport-agnostic ``StreamMessage`` objects; it never
imports OpenAI types (only the adapter does). The run lock is released on EVERY
exit path so a dropped turn can never brick a conversation at CONVERSATION_BUSY.
"""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.agent.actions import resolve_actions
from app.agent.adapter import (
    AdapterError,
    AssistantToolCall,
    Completed,
    InputItem,
    ModelAdapter,
    ModelMessage,
    TextDelta,
    ToolCall,
    ToolOutput,
)
from app.agent.prompt import CURRENT_PROMPT_VERSION, load_system_prompt
from app.agent.tools import ToolRegistry
from app.api.sse import StreamMessage
from app.core import ids
from app.core.errors import ErrorCode
from app.core.logging import get_logger, request_id_var
from app.domain.conversations.models import Conversation, Message, Source, Usage
from app.domain.conversations.repository import BeginTurnResult, ConversationRepository

logger = get_logger("app.orchestrator")

# Bound the model/tool loop so a misbehaving model can't call tools forever.
_MAX_TOOL_ROUNDS = 5

_LIMIT_REACHED_COPY = (
    "You've reached the current chat limit. You can still contact Cadre through the options below."
)
_GENERAL_FAILURE_COPY = (
    "I'm having trouble generating a response right now. "
    "You can try again or contact Cadre directly."
)


def _now() -> datetime:
    return datetime.now(UTC)


class ChatOrchestrator:
    def __init__(
        self,
        repo: ConversationRepository,
        adapter: ModelAdapter,
        *,
        tool_registry: ToolRegistry | None = None,
        prompt_version: str = CURRENT_PROMPT_VERSION,
    ) -> None:
        self._repo = repo
        self._adapter = adapter
        self._tool_registry = tool_registry
        self._prompt_version = prompt_version

    async def start_turn(self, conversation_id: str, content: str, cmid: str) -> BeginTurnResult:
        return await self._repo.begin_turn(conversation_id, content, cmid)

    def _build_window(self, conversation: Conversation) -> list[Message]:
        return [m for m in conversation.messages if m.status == "completed" and m.content]

    def _failed_event(self, code: str) -> StreamMessage:
        return StreamMessage(
            "response.failed",
            {
                "error": {
                    "code": code,
                    "message": _GENERAL_FAILURE_COPY,
                    "retryable": True,
                    "request_id": request_id_var.get(),
                }
            },
        )

    async def _persist_failed(
        self, conversation_id: str, run_id: str, parts: list[str], code: str, started: float
    ) -> None:
        failed = Message(
            id=ids.message_id(),
            role="assistant",
            content="".join(parts),
            status="failed",
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code=code,
            created_at=_now(),
        )
        await self._repo.fail_turn(conversation_id, run_id, failed)

    async def stream_started(
        self, conversation: Conversation, run_id: str, user_message: Message
    ) -> AsyncIterator[StreamMessage]:
        yield StreamMessage(
            "message.accepted",
            {"message_id": user_message.id, "client_message_id": user_message.client_message_id},
        )
        yield StreamMessage("response.started", {})

        instructions = load_system_prompt(self._prompt_version)
        input_items: list[InputItem] = [
            ModelMessage(role=m.role, content=m.content) for m in self._build_window(conversation)
        ]
        tools = self._tool_registry.specs() if self._tool_registry is not None else None

        started = time.perf_counter()
        parts: list[str] = []
        usage_in = 0
        usage_out = 0
        usage_seen = False
        canonical_answer_id: str | None = None
        sources: list[Source] = []
        seen_source_ids: set[str] = set()
        suggested_action_ids: list[str] = []
        finalized = False

        try:
            for _round in range(_MAX_TOOL_ROUNDS):
                # On the final permitted round, drop the tools so the model MUST
                # produce a text answer instead of another tool call — otherwise a
                # tool-happy model would leave us with an empty "completed" message.
                round_tools = tools if _round < _MAX_TOOL_ROUNDS - 1 else None
                round_tool_calls: list[ToolCall] = []
                async for event in self._adapter.send(
                    instructions=instructions, messages=input_items, tools=round_tools
                ):
                    if isinstance(event, TextDelta):
                        parts.append(event.text)
                        yield StreamMessage("response.delta", {"text": event.text})
                    elif isinstance(event, ToolCall):
                        round_tool_calls.append(event)
                    elif isinstance(event, Completed) and event.usage is not None:
                        usage_in += event.usage.input_tokens
                        usage_out += event.usage.output_tokens
                        usage_seen = True

                if not round_tool_calls or self._tool_registry is None:
                    break

                for call in round_tool_calls:
                    result = await self._tool_registry.execute(call.name, call.arguments)
                    if result.canonical_answer_id is not None:
                        canonical_answer_id = result.canonical_answer_id
                    for source in result.sources:
                        if source.source_id not in seen_source_ids:
                            seen_source_ids.add(source.source_id)
                            sources.append(source)
                    for action_id in result.suggested_action_ids:
                        if action_id not in suggested_action_ids:
                            suggested_action_ids.append(action_id)
                    input_items.append(AssistantToolCall(call.call_id, call.name, call.arguments))
                    input_items.append(ToolOutput(call.call_id, result.output))

            latency_ms = int((time.perf_counter() - started) * 1000)
            assistant = Message(
                id=ids.message_id(),
                role="assistant",
                content="".join(parts),
                status="completed",
                canonical_answer_id=canonical_answer_id,
                sources=sources,
                suggested_action_ids=suggested_action_ids,
                usage=Usage(input_tokens=usage_in, output_tokens=usage_out) if usage_seen else None,
                latency_ms=latency_ms,
                created_at=_now(),
            )
            stored = await self._repo.complete_turn(conversation.id, run_id, assistant)
            finalized = True
            if stored is None:
                yield self._failed_event(ErrorCode.INTERNAL_ERROR.value)
            else:
                logger.info(
                    "chat.turn.completed",
                    extra={
                        "context": {"conversation_id": conversation.id, "latency_ms": latency_ms}
                    },
                )
                yield StreamMessage(
                    "response.completed",
                    {
                        "assistant_message_id": assistant.id,
                        "suggested_actions": resolve_actions(suggested_action_ids),
                    },
                )
        except AdapterError as exc:
            finalized = True
            await self._persist_failed(conversation.id, run_id, parts, exc.code.value, started)
            logger.info(
                "chat.turn.failed",
                extra={
                    "context": {"conversation_id": conversation.id, "error_code": exc.code.value}
                },
            )
            yield self._failed_event(exc.code.value)
        except Exception:
            finalized = True
            await self._persist_failed(
                conversation.id, run_id, parts, ErrorCode.INTERNAL_ERROR.value, started
            )
            logger.error(
                "chat.turn.error",
                exc_info=True,
                extra={"context": {"conversation_id": conversation.id}},
            )
            yield self._failed_event(ErrorCode.INTERNAL_ERROR.value)
        finally:
            if not finalized:
                await self._persist_failed(
                    conversation.id, run_id, parts, ErrorCode.INTERNAL_ERROR.value, started
                )
                logger.info(
                    "chat.turn.abandoned",
                    extra={"context": {"conversation_id": conversation.id}},
                )

    async def stream_replay(
        self, conversation: Conversation, cmid: str
    ) -> AsyncIterator[StreamMessage]:
        """Replay a duplicate client_message_id's stored result (contracts §3.2)."""
        messages = conversation.messages
        user_index = next((i for i, m in enumerate(messages) if m.client_message_id == cmid), None)
        user_message = messages[user_index] if user_index is not None else None
        assistant = None
        if user_index is not None:
            assistant = next((m for m in messages[user_index + 1 :] if m.role == "assistant"), None)

        yield StreamMessage(
            "message.accepted",
            {"message_id": user_message.id if user_message else None, "client_message_id": cmid},
        )
        yield StreamMessage("response.started", {})
        if assistant is None:
            yield StreamMessage(
                "response.completed", {"assistant_message_id": None, "suggested_actions": []}
            )
            return
        if assistant.content:
            yield StreamMessage("response.delta", {"text": assistant.content})
        if assistant.status == "failed":
            yield self._failed_event(assistant.error_code or ErrorCode.INTERNAL_ERROR.value)
        else:
            yield StreamMessage(
                "response.completed",
                {
                    "assistant_message_id": assistant.id,
                    "suggested_actions": resolve_actions(assistant.suggested_action_ids),
                },
            )

    async def stream_limit_reached(self) -> AsyncIterator[StreamMessage]:
        yield StreamMessage("limit.reached", {"message": _LIMIT_REACHED_COPY})
