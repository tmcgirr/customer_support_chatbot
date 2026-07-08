"""Create-conversation endpoint (contracts §3.1)."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agent.prompt import CURRENT_PROMPT_VERSION
from app.api.deps import RateLimiterDep, RepoDep
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.core.security import mint_session_token

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])

WELCOME_TEXT = (
    "Hi, I'm Cadre AI's virtual assistant. I can help you learn about Cadre's services, "
    "explore whether we work with your industry, access client support, or connect with an "
    "AI strategist."
)
SUGGESTED_ACTIONS = [
    {"id": "company_overview", "label": "What does Cadre AI do?"},
    {"id": "industry_fit", "label": "Do you work with my industry?"},
    {"id": "strategy_call", "label": "Book a strategy call"},
    {"id": "portal_access", "label": "Access the client portal"},
]


class CreateConversationRequest(BaseModel):
    entry_page: str | None = None
    locale: str | None = None
    consent_version: str | None = None


class SuggestedAction(BaseModel):
    id: str
    label: str


class Welcome(BaseModel):
    text: str
    suggested_actions: list[SuggestedAction]


class CreateConversationResponse(BaseModel):
    conversation_id: str
    session_token: str
    welcome: Welcome


@router.post("", response_model=CreateConversationResponse)
async def create_conversation(
    body: CreateConversationRequest,
    request: Request,
    repo: RepoDep,
    rate_limiter: RateLimiterDep,
) -> CreateConversationResponse:
    settings = get_settings()
    allowed = await rate_limiter.hit(
        client_ip(request),
        limit=settings.ip_create_cap,
        window_seconds=settings.ip_create_window_seconds,
    )
    if not allowed:
        raise AppError(ErrorCode.RATE_LIMIT, retryable=True)
    conversation = await repo.create(
        entry_page=body.entry_page,
        locale=body.locale,
        consent_version=body.consent_version,
        prompt_version=CURRENT_PROMPT_VERSION,
        model=settings.openai_model,
    )
    return CreateConversationResponse(
        conversation_id=conversation.id,
        session_token=mint_session_token(conversation.id),
        welcome=Welcome(
            text=WELCOME_TEXT,
            suggested_actions=[SuggestedAction(**a) for a in SUGGESTED_ACTIONS],
        ),
    )
