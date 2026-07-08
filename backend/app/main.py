"""FastAPI application factory, lifespan, and middleware wiring."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.agent.adapter import OpenAIResponsesAdapter
from app.api import dev, health
from app.api.admin import router as admin_router
from app.api.public import conversations as public_conversations
from app.api.public import feedback as public_feedback
from app.api.public import messages as public_messages
from app.api.public import requests as public_requests
from app.core.config import get_settings
from app.core.db import create_mongo_client, get_database
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger, new_request_id, request_id_var
from app.domain.audit.repository import ensure_indexes as ensure_audit_indexes
from app.domain.canonical.repository import ensure_indexes as ensure_canonical_indexes
from app.domain.conversations.repository import ensure_indexes as ensure_conversation_indexes
from app.domain.feedback.repository import ensure_indexes as ensure_feedback_indexes
from app.domain.jobs.repository import ensure_indexes as ensure_job_indexes
from app.domain.knowledge.repository import ensure_indexes as ensure_knowledge_indexes
from app.domain.knowledge.search import KnowledgeSearch
from app.domain.ratelimit.repository import ensure_indexes as ensure_ratelimit_indexes
from app.domain.requests.repository import ensure_indexes as ensure_request_indexes

logger = get_logger("app.request")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = create_mongo_client()
    database = get_database(client)
    await ensure_conversation_indexes(database["conversations"])
    await ensure_knowledge_indexes(database["knowledge_sources"])
    await ensure_canonical_indexes(database["canonical_answers"])
    await ensure_request_indexes(database["requests"])
    await ensure_feedback_indexes(database["feedback"])
    await ensure_ratelimit_indexes(database["rate_limits"])
    await ensure_job_indexes(database["jobs"])
    await ensure_audit_indexes(database["audit"])
    app.state.mongo_client = client
    app.state.db = database
    app.state.adapter = OpenAIResponsesAdapter()
    app.state.knowledge_search = KnowledgeSearch()
    logger.info("app.startup", extra={"context": {"db": database.name}})
    try:
        yield
    finally:
        await app.state.adapter.aclose()
        await app.state.knowledge_search.aclose()
        client.close()
        logger.info("app.shutdown")


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(title="Cadre AI Support Chatbot", version=__version__, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = rid
        # IDs and metadata only — never the query string or any body.
        logger.info(
            "http.request",
            extra={
                "context": {
                    "method": request.method,
                    "route": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "request_id": rid,
                }
            },
        )
        return response

    register_exception_handlers(app)
    app.include_router(health.router)
    if settings.env == "dev":
        app.include_router(dev.router)  # /api/v1/dev/stream-test scaffold — dev only
    app.include_router(public_conversations.router)
    app.include_router(public_messages.router)
    app.include_router(public_requests.router)
    app.include_router(public_feedback.router)
    app.include_router(admin_router.router)
    return app


app = create_app()
