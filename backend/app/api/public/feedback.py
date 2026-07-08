"""Message feedback endpoint (contracts §3.5).

The message must belong to the session's conversation (ownership check) before
feedback is recorded.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import FeedbackRepoDep, RepoDep, TokenDep
from app.core import ids
from app.core.errors import AppError, ErrorCode
from app.domain.feedback.models import Feedback, FeedbackRating, FeedbackReason

router = APIRouter(prefix="/api/v1/messages", tags=["feedback"])


class FeedbackBody(BaseModel):
    rating: FeedbackRating
    reason: FeedbackReason | None = None
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/{message_id}/feedback")
async def submit_feedback(
    message_id: str,
    body: FeedbackBody,
    claims: TokenDep,
    conversation_repo: RepoDep,
    feedback_repo: FeedbackRepoDep,
) -> dict[str, str]:
    conversation = await conversation_repo.get_transcript(claims.cid)
    if conversation is None:
        raise AppError(ErrorCode.CONVERSATION_NOT_FOUND)
    if not any(message.id == message_id for message in conversation.messages):
        # Ownership: only messages in the caller's own conversation can be rated.
        raise AppError(ErrorCode.INVALID_REQUEST, "Message not found in this conversation.")

    feedback = Feedback(
        id=ids.feedback_id(),
        conversation_id=claims.cid,
        message_id=message_id,
        rating=body.rating,
        reason=body.reason,
        comment=body.comment,
        created_at=datetime.now(UTC),
    )
    await feedback_repo.record(feedback)
    return {"status": "received"}
