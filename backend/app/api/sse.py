"""Server-Sent Events helpers shared by the chat endpoints.

Anti-buffering headers (X-Accel-Buffering) keep deltas from being coalesced into
a single paint through proxies — the failure mode Phase 0's smoke test hunted.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from starlette.responses import StreamingResponse

from app.core.logging import request_id_var


@dataclass(frozen=True)
class StreamMessage:
    event: str
    data: dict[str, Any]


def format_sse(message: StreamMessage) -> str:
    return f"event: {message.event}\ndata: {json.dumps(message.data)}\n\n"


def sse_response(messages: AsyncIterator[StreamMessage]) -> StreamingResponse:
    # The body streams AFTER the request middleware has reset the request_id
    # contextvar, so capture it now and re-bind it for the duration of the stream
    # to keep turn logs correlated.
    rid = request_id_var.get()

    async def body() -> AsyncIterator[str]:
        token = request_id_var.set(rid)
        try:
            async for message in messages:
                yield format_sse(message)
        finally:
            request_id_var.reset(token)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
