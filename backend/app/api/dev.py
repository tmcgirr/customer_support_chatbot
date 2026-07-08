"""Development-only endpoints for verifying infrastructure shape.

`/api/v1/dev/stream-test` proves the full SSE pipe (browser -> FastAPI -> event
stream -> browser) end to end, including that deltas arrive *unbuffered* through
whatever proxy/load-balancer sits in front of the app. It emits the same event
names the real chat stream uses (contracts §3.2): `response.started`,
`response.delta`*, `response.completed`.
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from starlette.responses import StreamingResponse

router = APIRouter(prefix="/api/v1/dev", tags=["dev"])

# Ten tokens streamed one at a time so the browser can render progressively.
_DELTA_TOKENS: list[str] = [
    "Cadre ",
    "AI ",
    "walking ",
    "skeleton ",
    "is ",
    "streaming ",
    "one ",
    "token ",
    "at ",
    "a time.",
]

_DELTA_INTERVAL_SECONDS = 0.3


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _event_stream() -> AsyncIterator[str]:
    yield _sse("response.started", {})
    for index, token in enumerate(_DELTA_TOKENS):
        await asyncio.sleep(_DELTA_INTERVAL_SECONDS)
        yield _sse("response.delta", {"index": index, "text": token})
    yield _sse("response.completed", {"delta_count": len(_DELTA_TOKENS)})


@router.get("/stream-test")
async def stream_test() -> StreamingResponse:
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable proxy buffering (nginx / DO app platform) so deltas are not
            # coalesced into a single paint. This is the failure mode Phase 0 hunts.
            "X-Accel-Buffering": "no",
        },
    )
