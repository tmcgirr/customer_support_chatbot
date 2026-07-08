"""FastAPI application factory and middleware wiring."""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import dev, health
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger, new_request_id, request_id_var

logger = get_logger("app.request")


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(title="Cadre AI Support Chatbot", version=__version__)

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
        # IDs and metadata only — never the path's query string or any body.
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

    app.include_router(health.router)
    app.include_router(dev.router)
    return app


app = create_app()
