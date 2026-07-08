"""Tool-loop integration tests: the model calls a read-only tool, the app
executes it, resends the transcript, and the final answer + metadata persist."""

from datetime import UTC, datetime

import httpx

from app.agent.adapter import Completed, TextDelta, ToolCall, ToolOutput, Usage
from app.domain.canonical.models import CanonicalAnswer
from app.domain.canonical.repository import CanonicalAnswerRepository
from app.domain.knowledge.search import SearchHit, SearchResult
from tests.fakes import FakeAdapter, FakeKnowledgeSearch
from tests.integration.conftest import Collection
from tests.integration.test_chat import _auth, _create, _parse_sse, _send_sse


def _completed(usage_in: int = 10, usage_out: int = 5) -> Completed:
    return Completed(usage=Usage(input_tokens=usage_in, output_tokens=usage_out))


async def _seed_canonical(collection: Collection) -> str:
    now = datetime.now(UTC)
    answer = CanonicalAnswer(
        id="can_pricing_test",
        name="Pricing",
        intent="pricing",
        content="Cadre engagements are scoped to the business problem.",
        allowed_action_ids=["strategy_call"],
        mandatory_escalation=False,
        status="approved",
        owner="test",
        effective_date=now,
        review_date=now,
    )
    await CanonicalAnswerRepository(collection).upsert(answer)
    return answer.id


async def _assistant_doc(collection: Collection, cid: str) -> dict:
    doc = await collection.find_one({"_id": cid})
    assert doc is not None
    return next(m for m in doc["messages"] if m["role"] == "assistant")


async def test_canonical_tool_sets_answer_id_and_actions(
    client: httpx.AsyncClient,
    collection: Collection,
    canonical_collection: Collection,
    fake_adapter: FakeAdapter,
) -> None:
    answer_id = await _seed_canonical(canonical_collection)
    fake_adapter.set_rounds(
        [
            [
                ToolCall(
                    call_id="call_1", name="get_canonical_answer", arguments={"intent": "pricing"}
                ),
                _completed(),
            ],
            [
                TextDelta(text="Engagements are scoped to your needs. "),
                TextDelta(text="Want a strategy call?"),
                _completed(),
            ],
        ]
    )

    cid, token = await _create(client)
    events = await _send_sse(client, cid, token, "What do you charge?", "cmid_1")

    assert events[-1]["event"] == "response.completed"
    action_ids = [a["id"] for a in events[-1]["data"]["suggested_actions"]]
    assert "strategy_call" in action_ids

    # Two model rounds ran; the second carried the tool output back.
    assert len(fake_adapter.calls) == 2
    assert any(isinstance(m, ToolOutput) for m in fake_adapter.calls[1].messages)

    assistant = await _assistant_doc(collection, cid)
    assert assistant["canonical_answer_id"] == answer_id
    assert assistant["suggested_action_ids"] == ["strategy_call"]


async def test_search_tool_stores_sources(
    client: httpx.AsyncClient,
    collection: Collection,
    fake_adapter: FakeAdapter,
    fake_knowledge: FakeKnowledgeSearch,
) -> None:
    fake_knowledge.result = SearchResult(
        "ok",
        [
            SearchHit(
                source_id="kbs_industries",
                title="Industries",
                content="Cadre works with construction companies.",
                score=0.91,
                display_url="/knowledge/industries",
            )
        ],
    )
    fake_adapter.set_rounds(
        [
            [
                ToolCall(
                    call_id="call_1", name="search_knowledge", arguments={"query": "construction"}
                ),
                _completed(),
            ],
            [TextDelta(text="Yes, Cadre works with construction companies."), _completed()],
        ]
    )

    cid, token = await _create(client)
    events = await _send_sse(client, cid, token, "Do you work with construction?", "cmid_1")

    assert events[-1]["event"] == "response.completed"
    assert fake_knowledge.calls and fake_knowledge.calls[0][0] == "construction"

    assistant = await _assistant_doc(collection, cid)
    source_ids = [s["source_id"] for s in assistant["sources"]]
    assert "kbs_industries" in source_ids


async def test_portal_tool_offers_support_action(
    client: httpx.AsyncClient, collection: Collection, fake_adapter: FakeAdapter
) -> None:
    fake_adapter.set_rounds(
        [
            [ToolCall(call_id="call_1", name="get_portal_information", arguments={}), _completed()],
            [TextDelta(text="You can access the portal at the link."), _completed()],
        ]
    )

    cid, token = await _create(client)
    events = await _send_sse(client, cid, token, "How do I access the portal?", "cmid_1")

    assert events[-1]["event"] == "response.completed"
    action_ids = [a["id"] for a in events[-1]["data"]["suggested_actions"]]
    assert "portal_support" in action_ids


async def test_transcript_helpers_still_parse() -> None:
    # Guard the shared SSE parser against accidental format drift.
    events = _parse_sse('event: response.completed\ndata: {"assistant_message_id": "msg_1"}\n\n')
    assert events[0]["event"] == "response.completed"
    assert _auth("t")["Authorization"] == "Bearer t"
