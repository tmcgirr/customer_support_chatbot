"""Conversion-funnel endpoint: visited → asked → engaged → requested, overall and by
topic/intent, computed from conversation counts."""

from datetime import UTC, datetime

import httpx

from app.core.config import get_settings
from app.domain.conversations.models import Conversation, ConversationLabels
from tests.integration.conftest import Collection

_settings = get_settings()
ADMIN_AUTH = (_settings.admin_username, _settings.admin_password.get_secret_value())
VIEWER_AUTH = (_settings.viewer_username, _settings.viewer_password.get_secret_value())


def _convo(
    cid: str,
    *,
    message_count: int,
    outcome: str | None = None,
    topic: str | None = None,
    intent: str | None = None,
) -> dict:
    now = datetime.now(UTC)
    labels = (
        ConversationLabels(topic=topic, intent=intent or "other", method="rules", labeled_at=now)
        if topic
        else None
    )
    return Conversation(
        id=cid,
        status="completed",
        message_count=message_count,
        outcome=outcome,
        labels=labels,
        started_at=now,
        last_activity_at=now,
    ).model_dump(by_alias=True)


async def test_funnel_stages_overall_and_breakdowns(
    client: httpx.AsyncClient, collection: Collection
) -> None:
    await collection.insert_many(
        [
            _convo("c1", message_count=0, topic="pricing", intent="evaluate"),  # visited only
            _convo("c2", message_count=1, topic="pricing", intent="evaluate"),  # asked
            _convo(  # engaged (multi-turn) + requested (converted)
                "c3",
                message_count=3,
                outcome="strategy_call_requested",
                topic="security",
                intent="request_contact",
            ),
            _convo(  # SINGLE-TURN conversion: must fold up into asked+engaged (monotone)
                "c4",
                message_count=1,
                outcome="support_request_created",
                topic="portal",
                intent="request_contact",
            ),
        ]
    )
    resp = await client.get("/api/v1/admin/funnel", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    body = resp.json()

    # 4 visited; c2/c3/c4 asked; c3 (multi-turn) + c4 (converted→folded) engaged; c3/c4 requested.
    assert body["overall"] == {"visited": 4, "asked": 3, "engaged": 2, "requested": 2}
    # Monotone: every stage ≤ the prior, overall AND per bucket.
    for stage in [body["overall"], *body["by_topic"].values(), *body["by_intent"].values()]:
        assert stage["visited"] >= stage["asked"] >= stage["engaged"] >= stage["requested"]
    # The single-turn conversion counts as engaged for its topic (folded up).
    assert body["by_topic"]["portal"] == {"visited": 1, "asked": 1, "engaged": 1, "requested": 1}
    assert body["by_topic"]["pricing"] == {"visited": 2, "asked": 1, "engaged": 0, "requested": 0}


async def test_funnel_readable_by_viewer(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/funnel", auth=VIEWER_AUTH)
    assert resp.status_code == 200
    assert resp.json()["overall"] == {"visited": 0, "asked": 0, "engaged": 0, "requested": 0}
