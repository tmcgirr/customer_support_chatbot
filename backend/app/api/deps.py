"""FastAPI dependencies. Tests override these to inject a test DB + FakeAdapter."""

from typing import Annotated, cast

from fastapi import Depends, Header, Request

from app.agent.adapter import ModelAdapter
from app.agent.orchestrator import ChatOrchestrator
from app.core.errors import AppError, ErrorCode
from app.core.security import SessionClaims, verify_session_token
from app.domain.conversations.repository import ConversationRepository


def get_conversation_repository(request: Request) -> ConversationRepository:
    return ConversationRepository(request.app.state.db["conversations"])


def get_adapter(request: Request) -> ModelAdapter:
    return cast(ModelAdapter, request.app.state.adapter)


RepoDep = Annotated[ConversationRepository, Depends(get_conversation_repository)]
AdapterDep = Annotated[ModelAdapter, Depends(get_adapter)]


def get_orchestrator(repo: RepoDep, adapter: AdapterDep) -> ChatOrchestrator:
    return ChatOrchestrator(repo, adapter)


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
