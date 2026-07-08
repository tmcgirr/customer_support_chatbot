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
from app.domain.knowledge.search import KnowledgeSearch


def get_conversation_repository(request: Request) -> ConversationRepository:
    return ConversationRepository(request.app.state.db["conversations"])


def get_canonical_repository(request: Request) -> CanonicalAnswerRepository:
    return CanonicalAnswerRepository(request.app.state.db["canonical_answers"])


def get_adapter(request: Request) -> ModelAdapter:
    return cast(ModelAdapter, request.app.state.adapter)


def get_knowledge_search(request: Request) -> KnowledgeSearch:
    return cast(KnowledgeSearch, request.app.state.knowledge_search)


RepoDep = Annotated[ConversationRepository, Depends(get_conversation_repository)]
CanonicalRepoDep = Annotated[CanonicalAnswerRepository, Depends(get_canonical_repository)]
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
    return ChatOrchestrator(repo, adapter, tool_registry=registry)


OrchestratorDep = Annotated[ChatOrchestrator, Depends(get_orchestrator)]


def require_session(
    conversation_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> SessionClaims:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(ErrorCode.UNAUTHORIZED_SESSION)
    claims = verify_session_token(authorization[7:].strip())
    if claims.cid != conversation_id:
        raise AppError(ErrorCode.UNAUTHORIZED_SESSION)
    return claims


SessionDep = Annotated[SessionClaims, Depends(require_session)]
