"""End-to-end smoke of the run harness with the plumbing adapter (no real model): it drives
every case through the real orchestrator + repos and produces a scored RunResult."""

from typing import Any

from eval.config import EvalConfig
from eval.run import run_config
from tests.eval.conftest import Database


async def test_run_config_smoke_with_plumbing(db: Database) -> None:
    config = EvalConfig(name="test", model="m", prompt_version="sys-v1")
    cases: list[dict[str, Any]] = [
        {"id": "t_001", "turns": ["Hello there, a question"], "assert": {}},
        {"id": "t_002", "turns": ["Hi again"], "assert": {"must_not_contain": ["zzz"]}},
        # Expects canonical routing the plumbing adapter never does → a real FAIL is captured.
        {"id": "t_003", "turns": ["pricing?"], "assert": {"must_use_canonical": "pricing"}},
    ]

    run = await run_config(db, {}, config, cases, fake=True)

    assert run.config.name == "test" and run.total == 3
    assert run.passed == 2  # first two pass; the canonical-routing one fails under plumbing
    assert run.score == 2 / 3
    ids = {c.id: c for c in run.cases}
    assert ids["t_003"].passed is False and ids["t_003"].failures
    assert ids["t_001"].routed_intent is None  # plumbing does no routing
    assert all(c.latency_ms >= 0 for c in run.cases)
