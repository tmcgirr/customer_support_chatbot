"""FastAPI dependencies. Tests override these to inject a test DB + fakes."""

from typing import Annotated, cast

from fastapi import Depends, Header, Request

from app.agent.adapter import ModelAdapter
from app.agent.orchestrator import ChatOrchestrator
from app.agent.tools import ToolRegistry
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import SessionClaims, verify_session_token
from app.domain.canonical.repository import CanonicalAnswerRepository
from app.domain.conversations.repository import ConversationRepository
from app.domain.feedback.repository import FeedbackRepository
from app.domain.jobs.repository import JobRepository
from app.domain.knowledge.search import KnowledgeSearch
from app.domain.ratelimit.repository import RateLimitRepository
from app.domain.requests.repository import RequestRepository
from app.domain.requests.service import RequestService


def get_conversation_repository(request: Request) -> ConversationRepository:
    return ConversationRepository(request.app.state.db["conversations"])


def get_rate_limiter(request: Request) -> RateLimitRepository:
    return RateLimitRepository(
        request.app.state.db["rate_limits"],
        secret=get_settings().session_secret.get_secret_value(),
    )


def get_canonical_repository(request: Request) -> CanonicalAnswerRepository:
    return CanonicalAnswerRepository(request.app.state.db["canonical_answers"])


def get_request_repository(request: Request) -> RequestRepository:
    return RequestRepository(request.app.state.db["requests"])


def get_job_repository(request: Request) -> JobRepository:
    return JobRepository(request.app.state.db["jobs"])


def get_feedback_repository(request: Request) -> FeedbackRepository:
    return FeedbackRepository(request.app.state.db["feedback"])


def get_adapter(request: Request) -> ModelAdapter:
    return cast(ModelAdapter, request.app.state.adapter)


def get_knowledge_search(request: Request) -> KnowledgeSearch:
    return cast(KnowledgeSearch, request.app.state.knowledge_search)


RepoDep = Annotated[ConversationRepository, Depends(get_conversation_repository)]
RateLimiterDep = Annotated[RateLimitRepository, Depends(get_rate_limiter)]
CanonicalRepoDep = Annotated[CanonicalAnswerRepository, Depends(get_canonical_repository)]
RequestRepoDep = Annotated[RequestRepository, Depends(get_request_repository)]
FeedbackRepoDep = Annotated[FeedbackRepository, Depends(get_feedback_repository)]
AdapterDep = Annotated[ModelAdapter, Depends(get_adapter)]
KnowledgeSearchDep = Annotated[KnowledgeSearch, Depends(get_knowledge_search)]


def get_tool_registry(knowledge: KnowledgeSearchDep, canonical: CanonicalRepoDep) -> ToolRegistry:
    settings = get_settings()
    return ToolRegistry(
        knowledge,
        canonical,
        portal_url=settings.portal_url,
        portal_reset_instructions=settings.portal_reset_instructions,
    )


ToolRegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]


def get_orchestrator(
    repo: RepoDep, adapter: AdapterDep, registry: ToolRegistryDep
) -> ChatOrchestrator:
    return ChatOrchestrator(
        repo,
        adapter,
        tool_registry=registry,
        lock_stale_seconds=get_settings().lock_stale_seconds,
    )


OrchestratorDep = Annotated[ChatOrchestrator, Depends(get_orchestrator)]


JobRepoDep = Annotated[JobRepository, Depends(get_job_repository)]


def get_request_service(
    request_repo: RequestRepoDep, conversation_repo: RepoDep, jobs: JobRepoDep
) -> RequestService:
    return RequestService(
        request_repo,
        conversation_repo,
        jobs=jobs,
        enable_delivery=get_settings().enable_delivery,
    )


RequestServiceDep = Annotated[RequestService, Depends(get_request_service)]


def _bearer_claims(authorization: str | None) -> SessionClaims:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(ErrorCode.UNAUTHORIZED_SESSION)
    return verify_session_token(authorization[7:].strip())


def require_session(
    conversation_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> SessionClaims:
    """Session bound to a path conversation_id (chat + transcript endpoints)."""
    claims = _bearer_claims(authorization)
    if claims.cid != conversation_id:
        raise AppError(ErrorCode.UNAUTHORIZED_SESSION)
    return claims


def require_token(authorization: Annotated[str | None, Header()] = None) -> SessionClaims:
    """Valid session token, no path binding (requests + feedback verify the cid inline)."""
    return _bearer_claims(authorization)


SessionDep = Annotated[SessionClaims, Depends(require_session)]
TokenDep = Annotated[SessionClaims, Depends(require_token)]
