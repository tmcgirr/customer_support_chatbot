"""Message feedback document (contracts §7)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FeedbackRating = Literal["helpful", "not_helpful"]
FeedbackReason = Literal["incorrect", "unclear", "did_not_answer", "need_person", "other"]


class Feedback(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    conversation_id: str
    message_id: str
    rating: FeedbackRating
    reason: FeedbackReason | None = None
    comment: str | None = None
    created_at: datetime
