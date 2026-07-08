"""Send-message (SSE) and transcript endpoints (contracts §3.2, §3.3)."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from app.api.deps import OrchestratorDep, RepoDep, SessionDep
from app.api.sse import sse_response
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode

router = APIRouter(prefix="/api/v1/conversations", tags=["messages"])


class SendMessageRequest(BaseModel):
    content: str
    client_message_id: str


class PublicMessage(BaseModel):
    id: str
    role: str
    content: str
    status: str
    suggested_action_ids: list[str]
    created_at: datetime


class TranscriptResponse(BaseModel):
    conversation_id: str
    messages: list[PublicMessage]


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    orchestrator: OrchestratorDep,
    _session: SessionDep,
) -> StreamingResponse:
    content = body.content
    if not content.strip():
        raise AppError(ErrorCode.INVALID_REQUEST, "Message content is required.")
    if len(content) > get_settings().message_max_chars:
        raise AppError(ErrorCode.MESSAGE_TOO_LONG)

    result = await orchestrator.start_turn(conversation_id, content, body.client_message_id)
    if result.outcome == "NOT_FOUND":
        raise AppError(ErrorCode.CONVERSATION_NOT_FOUND)
    if result.outcome == "BUSY":
        raise AppError(ErrorCode.CONVERSATION_BUSY)
    if result.outcome == "CAP_REACHED":
        return sse_response(orchestrator.stream_limit_reached())
    if result.outcome == "DUPLICATE":
        assert result.conversation is not None
        return sse_response(orchestrator.stream_replay(result.conversation, body.client_message_id))

    conversation = result.conversation
    run_id = result.run_id
    user_message = result.user_message
    assert conversation is not None and run_id is not None and user_message is not None
    return sse_response(orchestrator.stream_started(conversation, run_id, user_message))


@router.get("/{conversation_id}/messages", response_model=TranscriptResponse)
async def get_transcript(
    conversation_id: str, repo: RepoDep, _session: SessionDep
) -> TranscriptResponse:
    conversation = await repo.get_transcript(conversation_id)
    if conversation is None:
        raise AppError(ErrorCode.CONVERSATION_NOT_FOUND)
    return TranscriptResponse(
        conversation_id=conversation.id,
        messages=[
            PublicMessage(
                id=m.id,
                role=m.role,
                content=m.content,
                status=m.status,
                suggested_action_ids=m.suggested_action_ids,
                created_at=m.created_at,
            )
            for m in conversation.messages
        ],
    )
