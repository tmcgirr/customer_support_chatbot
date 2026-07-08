"""Chat orchestrator — the turn loop (ADR §3.1).

begin_turn (atomic lock+append) → build the window (system prompt + transcript;
the cap guarantees it fits, no summarization at POC) → stream from the adapter,
relaying deltas as SSE → complete_turn / fail_turn, persisting the assistant
message with usage, latency, and any error_code.

The orchestrator yields transport-agnostic ``StreamMessage`` objects; the route
formats them as SSE. It never imports OpenAI types (only the adapter does).

Lock discipline: the run lock is released on EVERY exit path — success, adapter
failure, unexpected error, or client disconnect — so a conversation can never be
bricked at CONVERSATION_BUSY by a dropped turn.
"""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.agent.actions import resolve_actions
from app.agent.adapter import (
    AdapterError,
    Completed,
    ModelAdapter,
    ModelMessage,
    TextDelta,
    ToolCall,
)
from app.agent.prompt import CURRENT_PROMPT_VERSION, load_system_prompt
from app.api.sse import StreamMessage
from app.core import ids
from app.core.errors import ErrorCode
from app.core.logging import get_logger, request_id_var
from app.domain.conversations.models import Conversation, Message, Usage
from app.domain.conversations.repository import BeginTurnResult, ConversationRepository

logger = get_logger("app.orchestrator")

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
        prompt_version: str = CURRENT_PROMPT_VERSION,
    ) -> None:
        self._repo = repo
        self._adapter = adapter
        self._prompt_version = prompt_version

    async def start_turn(self, conversation_id: str, content: str, cmid: str) -> BeginTurnResult:
        return await self._repo.begin_turn(conversation_id, content, cmid)

    def _build_window(self, conversation: Conversation) -> list[ModelMessage]:
        return [
            ModelMessage(role=m.role, content=m.content)
            for m in conversation.messages
            if m.status == "completed" and m.content
        ]

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
        window = self._build_window(conversation)
        started = time.perf_counter()
        parts: list[str] = []
        usage: Usage | None = None
        finalized = False

        try:
            async for event in self._adapter.send(instructions=instructions, messages=window):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                    yield StreamMessage("response.delta", {"text": event.text})
                elif isinstance(event, ToolCall):
                    continue  # No tools registered at Phase 2; Phase 3 dispatches these.
                elif isinstance(event, Completed) and event.usage is not None:
                    usage = Usage(
                        input_tokens=event.usage.input_tokens,
                        output_tokens=event.usage.output_tokens,
                    )

            latency_ms = int((time.perf_counter() - started) * 1000)
            assistant = Message(
                id=ids.message_id(),
                role="assistant",
                content="".join(parts),
                status="completed",
                usage=usage,
                latency_ms=latency_ms,
                created_at=_now(),
            )
            stored = await self._repo.complete_turn(conversation.id, run_id, assistant)
            finalized = True
            if stored is None:
                # The lock was reclaimed (stale sweep / concurrent finish); this
                # turn's message was not appended, so don't report success.
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
                        "suggested_actions": resolve_actions(assistant.suggested_action_ids),
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
            # exc_info logs the exception TYPE only (JsonFormatter drops the message).
            logger.error(
                "chat.turn.error",
                exc_info=True,
                extra={"context": {"conversation_id": conversation.id}},
            )
            yield self._failed_event(ErrorCode.INTERNAL_ERROR.value)
        finally:
            if not finalized:
                # Client disconnected / task cancelled mid-stream: release the lock
                # (best-effort; no yield is allowed while unwinding a GeneratorExit).
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
