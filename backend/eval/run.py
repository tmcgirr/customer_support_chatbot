"""Golden evaluation runner (ADR-018) — the release gate.

    uv run python -m eval.run          # real model: the gate (exits non-zero on failure)
    uv run python -m eval.run --fake   # plumbing adapter: proves the harness runs (exits 0)

Loads eval/golden_set.yaml, drives each case through the real orchestrator +
read-only tools, evaluates the assertions, and prints a per-case report.
"""

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import yaml
from motor.motor_asyncio import AsyncIOMotorClient

from app.agent.adapter import (
    Completed,
    InputItem,
    OpenAIResponsesAdapter,
    StreamEvent,
    TextDelta,
    ToolSpec,
)
from app.agent.orchestrator import ChatOrchestrator
from app.agent.tools import ToolRegistry
from app.core import ids
from app.core.config import get_settings
from app.domain.canonical.repository import CanonicalAnswerRepository
from app.domain.conversations.repository import ConversationRepository, ensure_indexes
from app.domain.knowledge.search import KnowledgeSearch
from eval.assertions import TurnResult, evaluate

GOLDEN_SET = Path(__file__).parent / "golden_set.yaml"


class _PlumbingAdapter:
    """Canned response so --fake proves the runner drives every case."""

    async def send(
        self,
        *,
        instructions: str,
        messages: list[InputItem],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        yield TextDelta(text="Plumbing-mode response.")
        yield Completed(usage=None)


async def _run_turn(
    orchestrator: ChatOrchestrator,
    repo: ConversationRepository,
    canonical_by_id: dict[str, tuple[str, bool]],
    conversation_id: str,
    content: str,
) -> TurnResult:
    result = await orchestrator.start_turn(conversation_id, content, ids.prefixed_id("cmid"))
    if (
        result.outcome != "STARTED"
        or result.conversation is None
        or result.run_id is None
        or result.user_message is None
    ):
        raise RuntimeError(f"begin_turn returned {result.outcome}")

    parts: list[str] = []
    async for message in orchestrator.stream_started(
        result.conversation, result.run_id, result.user_message
    ):
        if message.event == "response.delta":
            parts.append(str(message.data["text"]))
        elif message.event == "response.failed":
            raise RuntimeError(f"response.failed: {message.data}")

    conversation = await repo.get_transcript(conversation_id)
    assert conversation is not None
    assistant = [m for m in conversation.messages if m.role == "assistant"][-1]
    intent, mandatory = canonical_by_id.get(assistant.canonical_answer_id or "", (None, False))
    return TurnResult(
        text="".join(parts),
        canonical_intent=intent,
        canonical_answer_id=assistant.canonical_answer_id,
        mandatory_escalation=mandatory,
        suggested_action_ids=list(assistant.suggested_action_ids),
        source_ids=[s.source_id for s in assistant.sources],
    )


async def _run_case(
    orchestrator: ChatOrchestrator,
    repo: ConversationRepository,
    canonical_by_id: dict[str, tuple[str, bool]],
    case: dict[str, Any],
    show: bool = False,
) -> list[str]:
    conversation = await repo.create(entry_page="eval")
    last: TurnResult | None = None
    for content in case["turns"]:
        last = await _run_turn(orchestrator, repo, canonical_by_id, conversation.id, content)
    assert last is not None
    if show:
        print(f"      · intent={last.canonical_intent} actions={last.suggested_action_ids}")
        print(f"      · text: {last.text!r}")
    return evaluate(case.get("assert", {}), last)


async def main(fake: bool, id_filter: str = "", show: bool = False) -> int:
    settings = get_settings()
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        settings.mongo_uri.get_secret_value(), tz_aware=True
    )
    database = client[settings.mongo_db_name]
    await ensure_indexes(database["conversations"])
    repo = ConversationRepository(database["conversations"])
    canonical_repo = CanonicalAnswerRepository(database["canonical_answers"])
    canonical_by_id = {
        answer.id: (answer.intent, answer.mandatory_escalation)
        for answer in await canonical_repo.list_answers()
    }
    knowledge = KnowledgeSearch()
    registry = ToolRegistry(
        knowledge,
        canonical_repo,
        portal_url=settings.portal_url,
        portal_reset_instructions=settings.portal_reset_instructions,
    )
    adapter: Any = _PlumbingAdapter() if fake else OpenAIResponsesAdapter()
    orchestrator = ChatOrchestrator(repo, adapter, tool_registry=registry)

    cases: list[dict[str, Any]] = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
    if id_filter:
        cases = [case for case in cases if id_filter in case.get("id", "")]
    failed = 0
    for case in cases:
        try:
            failures = await _run_case(orchestrator, repo, canonical_by_id, case, show=show)
        except Exception as exc:  # a crashed case is a failed case
            failures = [f"error: {type(exc).__name__}: {exc}"]
        if failures:
            failed += 1
            print(f"FAIL {case.get('id', '?')}")
            for failure in failures:
                print(f"      - {failure}")
        else:
            print(f"PASS {case.get('id', '?')}")

    await knowledge.aclose()
    client.close()

    total = len(cases)
    suffix = "  [PLUMBING — not gated]" if fake else ""
    print(f"\n{total - failed}/{total} cases passed{suffix}")
    if fake:
        return 0
    return 1 if failed else 0


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Cadre AI golden evaluation gate")
    parser.add_argument(
        "--fake", action="store_true", help="Use a plumbing adapter (always exits 0)"
    )
    parser.add_argument("--filter", default="", help="Run only cases whose id contains this")
    parser.add_argument(
        "--show", action="store_true", help="Print each case's response text + routed intent"
    )
    args = parser.parse_args()
    return asyncio.run(main(fake=args.fake, id_filter=args.filter, show=args.show))


if __name__ == "__main__":
    sys.exit(_cli())
