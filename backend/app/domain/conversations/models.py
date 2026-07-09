"""Conversation document model (contracts §7).

MongoDB is the single source of truth; messages are embedded in the conversation
document and the whole thing is read/written atomically. These Pydantic models
are the validated shape of that document — the ``_id`` is the local ULID.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRole = Literal["user", "assistant"]
MessageStatus = Literal["completed", "failed", "partial"]
ConversationStatus = Literal["active", "completed", "abandoned", "blocked", "deleted"]


class Source(BaseModel):
    source_id: str
    title: str
    display_url: str


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class Message(BaseModel):
    # protected_namespaces=() so the trace field named `model` is allowed.
    model_config = ConfigDict(protected_namespaces=())

    id: str
    role: MessageRole
    content: str
    client_message_id: str | None = None  # user messages only
    status: MessageStatus = "completed"
    canonical_answer_id: str | None = None
    sources: list[Source] = Field(default_factory=list)
    suggested_action_ids: list[str] = Field(default_factory=list)
    usage: Usage | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    # Trace metadata (assistant messages): which prompt/model answered, plus a
    # per-turn id for log correlation. `model` reflects the fallback if it was used.
    prompt_version: str | None = None
    model: str | None = None
    trace_id: str | None = None
    created_at: datetime


class ActiveRun(BaseModel):
    run_id: str
    started_at: datetime


class UnsupportedQuestion(BaseModel):
    question: str
    at: datetime


class ConversationLabels(BaseModel):
    """Computed topic/intent labels for analytics (V1.5). Derived AFTER a conversation
    ends by the async labeler — never on the request path. ``method`` records whether a
    deterministic rule or the model produced them (hybrid pipeline)."""

    topic: str
    intent: str
    method: Literal["rules", "model"]
    labeled_at: datetime


class Conversation(BaseModel):
    # populate_by_name lets us construct with `id=` while Mongo stores `_id`;
    # protected_namespaces=() allows the contract field named `model`.
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())

    id: str = Field(alias="_id")
    status: ConversationStatus = "active"
    entry_page: str | None = None
    locale: str | None = None
    consent_version: str | None = None
    active_run: ActiveRun | None = None
    message_count: int = 0
    message_cap: int = 40
    outcome: str | None = None
    unsupported_questions: list[UnsupportedQuestion] = Field(default_factory=list)
    labels: ConversationLabels | None = None  # computed post-hoc by the analytics labeler
    prompt_version: str | None = None
    model: str | None = None
    schema_version: int = 1
    started_at: datetime
    last_activity_at: datetime
    completed_at: datetime | None = None
    deletion_status: str | None = None
    messages: list[Message] = Field(default_factory=list)
