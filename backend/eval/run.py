"""Golden evaluation runner (ADR-018) — the release GATE and a standalone dev/test tool.

Gate (unchanged, CI-wired):
    uv run python -m eval.run              # real model: exits non-zero on any failure
    uv run python -m eval.run --fake       # plumbing adapter: proves the harness runs (exits 0)
    uv run python -m eval.run --show        # + per-case response text + routed intent
    uv run python -m eval.run --filter prc  # only cases whose id contains this

Developer/test tooling (evaluate performance + routing across prompts/models — never in the
app or admin portal):
    uv run python -m eval.run --report out.html            # gate + a self-contained HTML report
    uv run python -m eval.run --json out.json              # gate + structured results JSON
    uv run python -m eval.run --model MODEL --prompt-version sys-v2   # one-off override
    uv run python -m eval.run --compare configs.yaml --report out.html  # A-B configs, rank, report

Each case is driven through the REAL orchestrator + read-only tools, so routing (which canonical
intent fired, which action was offered) is measured exactly as it ships.
"""

import argparse
import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.agent.adapter import (
    Completed,
    InputItem,
    ModelAdapter,
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
from eval.config import EvalConfig, current_config, load_configs
from eval.report import render_html
from eval.results import CaseResult, RunResult

GOLDEN_SET = Path(__file__).parent / "golden_set.yaml"

Database = AsyncIOMotorDatabase[dict[str, Any]]
CanonicalById = dict[str, tuple[str, bool]]


class _PlumbingAdapter:
    """Canned response so --fake proves the runner drives every case without spending API $."""

    async def send(
        self,
        *,
        instructions: str,
        messages: list[InputItem],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        yield TextDelta(text="Plumbing-mode response.")
        yield Completed(usage=None)

    async def classify(self, *, instructions: str, text: str) -> str:
        return "{}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


async def _last_turn(
    orchestrator: ChatOrchestrator,
    repo: ConversationRepository,
    canonical_by_id: CanonicalById,
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
    canonical_by_id: CanonicalById,
    case: dict[str, Any],
    show: bool,
) -> CaseResult:
    cid = str(case.get("id", "?"))
    start = time.perf_counter()
    try:
        conversation = await repo.create(entry_page="eval")
        last: TurnResult | None = None
        for content in case["turns"]:
            last = await _last_turn(orchestrator, repo, canonical_by_id, conversation.id, content)
        assert last is not None
        failures = evaluate(case.get("assert", {}), last)
        result = CaseResult(
            id=cid,
            passed=not failures,
            failures=failures,
            routed_intent=last.canonical_intent,
            actions=list(last.suggested_action_ids),
            text=last.text,
        )
    except Exception as exc:  # a crashed case is a failed case
        result = CaseResult(id=cid, passed=False, failures=[f"error: {type(exc).__name__}: {exc}"])
    result.latency_ms = int((time.perf_counter() - start) * 1000)
    if show:
        print(f"      · intent={result.routed_intent} actions={result.actions}")
        print(f"      · text: {result.text!r}")
    return result


def _build_adapter(config: EvalConfig, *, fake: bool, adapter: ModelAdapter | None) -> ModelAdapter:
    if adapter is not None:
        return adapter
    if fake:
        return _PlumbingAdapter()
    return OpenAIResponsesAdapter(model=config.model, fallback_model=config.fallback_model)


async def run_config(
    database: Database,
    canonical_by_id: CanonicalById,
    config: EvalConfig,
    cases: list[dict[str, Any]],
    *,
    fake: bool = False,
    adapter: ModelAdapter | None = None,
    show: bool = False,
) -> RunResult:
    """Drive the whole golden set once under ``config`` and return a scored RunResult."""
    repo = ConversationRepository(database["conversations"])
    canonical_repo = CanonicalAnswerRepository(database["canonical_answers"])
    knowledge = KnowledgeSearch()
    settings = get_settings()
    registry = ToolRegistry(
        knowledge,
        canonical_repo,
        portal_url=settings.portal_url,
        portal_reset_instructions=settings.portal_reset_instructions,
    )
    orchestrator = ChatOrchestrator(
        repo,
        _build_adapter(config, fake=fake, adapter=adapter),
        tool_registry=registry,
        prompt_version=config.prompt_version,
    )
    results = [await _run_case(orchestrator, repo, canonical_by_id, case, show) for case in cases]
    await knowledge.aclose()
    return RunResult(config=config, generated_at=datetime.now(UTC), cases=results)


def _write_output(path_str: str, content: str) -> str:
    """Write an output artifact, creating parent dirs. Returns a status line; an I/O error
    is reported (not raised) so it can never flip the gate's exit code."""
    try:
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"wrote {path_str}"
    except OSError as exc:
        return f"WARNING: could not write {path_str}: {exc}"


def _load_cases(id_filter: str) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
    return [c for c in cases if id_filter in c.get("id", "")] if id_filter else cases


def _print_run(run: RunResult, *, per_case: bool) -> None:
    if per_case:
        for case in run.cases:
            if case.passed:
                print(f"PASS {case.id}")
            else:
                print(f"FAIL {case.id}")
                for failure in case.failures:
                    print(f"      - {failure}")
    print(f"  {run.config.name}: {run.passed}/{run.total} passed ({round(run.score * 100)}%)")


async def main(
    *,
    fake: bool = False,
    id_filter: str = "",
    show: bool = False,
    compare: str = "",
    report: str = "",
    json_out: str = "",
    model: str = "",
    prompt_version: str = "",
) -> int:
    settings = get_settings()
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        settings.mongo_uri.get_secret_value(), tz_aware=True
    )
    database = client[settings.mongo_db_name]
    await ensure_indexes(database["conversations"])
    canonical_repo = CanonicalAnswerRepository(database["canonical_answers"])
    canonical_by_id: CanonicalById = {
        answer.id: (answer.intent, answer.mandatory_escalation)
        for answer in await canonical_repo.list_answers()
    }
    cases = _load_cases(id_filter)

    if compare:
        configs = load_configs(Path(compare))
        gated = False  # comparison is exploratory dev tooling, not the CI gate
    else:
        base = current_config()
        configs = [
            EvalConfig(
                name="override" if (model or prompt_version) else base.name,
                model=model or base.model,
                fallback_model=base.fallback_model,
                prompt_version=prompt_version or base.prompt_version,
            )
        ]
        gated = not fake  # the plain baseline run is the CI gate

    runs: list[RunResult] = []
    for config in configs:
        run = await run_config(database, canonical_by_id, config, cases, fake=fake, show=show)
        runs.append(run)
        _print_run(run, per_case=not compare)

    client.close()

    # Writing an output artifact must NEVER change the gate's exit code — the gate reflects
    # the eval result, not I/O. A bad path warns (and makes the parent dir) but doesn't crash.
    if json_out:
        payload = json.dumps({"runs": [r.as_dict() for r in runs]}, indent=2)
        print(await asyncio.to_thread(_write_output, json_out, payload))
    if report:
        print(await asyncio.to_thread(_write_output, report, render_html(runs)))

    if gated and any(not c.passed for r in runs for c in r.cases):
        return 1
    return 0


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Cadre AI golden evaluation gate + dev tool")
    parser.add_argument("--fake", action="store_true", help="Plumbing adapter (always exits 0)")
    parser.add_argument("--filter", default="", help="Run only cases whose id contains this")
    parser.add_argument("--show", action="store_true", help="Print each case's response + intent")
    parser.add_argument("--compare", default="", help="YAML of named configs to A-B + rank")
    parser.add_argument("--report", default="", help="Write a self-contained HTML report here")
    parser.add_argument("--json", dest="json_out", default="", help="Write results JSON here")
    parser.add_argument("--model", default="", help="Override the model for a one-off run")
    parser.add_argument(
        "--prompt-version", default="", help="Override the system-prompt version for a one-off run"
    )
    args = parser.parse_args()
    return asyncio.run(
        main(
            fake=args.fake,
            id_filter=args.filter,
            show=args.show,
            compare=args.compare,
            report=args.report,
            json_out=args.json_out,
            model=args.model,
            prompt_version=args.prompt_version,
        )
    )


if __name__ == "__main__":
    sys.exit(_cli())
