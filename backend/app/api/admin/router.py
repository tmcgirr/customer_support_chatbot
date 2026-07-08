"""Read-only admin API (contracts §4). Every route requires admin Basic auth.

PII is masked by default (contracts §10): request contact emails and any email
embedded in a conversation transcript are shown as ``a***@acme.com``.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.admin.auth import AdminDep
from app.api.deps import RepoDep, RequestRepoDep
from app.core.errors import AppError, ErrorCode
from app.core.masking import mask_email, mask_pii_in_text

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class ConversationStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_outcome: dict[str, int]


class RequestStats(BaseModel):
    total: int
    by_type: dict[str, int]
    by_status: dict[str, int]


class DashboardResponse(BaseModel):
    conversations: ConversationStats
    requests: RequestStats
    unresolved_questions: int


class ConversationSummary(BaseModel):
    conversation_id: str
    status: str
    outcome: str | None
    message_count: int
    started_at: datetime
    last_activity_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]


class AdminMessage(BaseModel):
    id: str
    role: str
    content: str
    status: str
    created_at: datetime


class ConversationDetail(BaseModel):
    conversation_id: str
    status: str
    outcome: str | None
    started_at: datetime
    messages: list[AdminMessage]


class AdminRequest(BaseModel):
    request_id: str
    type: str
    status: str
    reference: str
    contact_email: str
    contact_company: str | None
    conversation_id: str
    created_at: datetime


class RequestListResponse(BaseModel):
    requests: list[AdminRequest]


class UnresolvedQuestion(BaseModel):
    question: str
    at: datetime
    conversation_id: str


class UnresolvedListResponse(BaseModel):
    questions: list[UnresolvedQuestion]


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    _admin: AdminDep, repo: RepoDep, request_repo: RequestRepoDep
) -> DashboardResponse:
    unresolved = await repo.list_unsupported(limit=1000)
    return DashboardResponse(
        conversations=ConversationStats(
            total=await repo.total(),
            by_status=await repo.count_by("status"),
            by_outcome=await repo.count_by("outcome"),
        ),
        requests=RequestStats(
            total=await request_repo.total(),
            by_type=await request_repo.count_by("type"),
            by_status=await request_repo.count_by("status"),
        ),
        unresolved_questions=len(unresolved),
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(_admin: AdminDep, repo: RepoDep) -> ConversationListResponse:
    conversations = await repo.list_recent()
    return ConversationListResponse(
        conversations=[
            ConversationSummary(
                conversation_id=c.id,
                status=c.status,
                outcome=c.outcome,
                message_count=c.message_count,
                started_at=c.started_at,
                last_activity_at=c.last_activity_at,
            )
            for c in conversations
        ]
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def conversation_detail(
    conversation_id: str, _admin: AdminDep, repo: RepoDep
) -> ConversationDetail:
    conversation = await repo.get_transcript(conversation_id)
    if conversation is None:
        raise AppError(ErrorCode.CONVERSATION_NOT_FOUND)
    return ConversationDetail(
        conversation_id=conversation.id,
        status=conversation.status,
        outcome=conversation.outcome,
        started_at=conversation.started_at,
        messages=[
            AdminMessage(
                id=m.id,
                role=m.role,
                content=mask_pii_in_text(m.content),
                status=m.status,
                created_at=m.created_at,
            )
            for m in conversation.messages
        ],
    )


@router.get("/requests", response_model=RequestListResponse)
async def list_requests(
    _admin: AdminDep,
    request_repo: RequestRepoDep,
    request_type: Annotated[str | None, Query(alias="type")] = None,
    request_status: Annotated[str | None, Query(alias="status")] = None,
) -> RequestListResponse:
    records = await request_repo.list_filtered(
        type_filter=request_type, status_filter=request_status
    )
    return RequestListResponse(
        requests=[
            AdminRequest(
                request_id=r.id,
                type=r.type,
                status=r.status,
                reference=r.reference,
                contact_email=mask_email(r.contact.email),
                contact_company=r.contact.company,
                conversation_id=r.conversation_id,
                created_at=r.created_at,
            )
            for r in records
        ]
    )


@router.get("/unresolved-questions", response_model=UnresolvedListResponse)
async def unresolved_questions(_admin: AdminDep, repo: RepoDep) -> UnresolvedListResponse:
    items = await repo.list_unsupported()
    return UnresolvedListResponse(
        questions=[
            UnresolvedQuestion(
                question=mask_pii_in_text(item["question"]),
                at=item["at"],
                conversation_id=item["conversation_id"],
            )
            for item in items
        ]
    )
