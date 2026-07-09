"""Structured evaluation results + scoring (pure, so they unit-test without the model/DB).

A ``RunResult`` is one config's pass over the golden set; a set of them is what the report
ranks. Score = pass rate (0..1); routing is captured per case (``routed_intent``) since a
core purpose is judging routing changes across prompts/models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from eval.config import EvalConfig


@dataclass
class CaseResult:
    id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    routed_intent: str | None = None
    actions: list[str] = field(default_factory=list)
    text: str = ""
    latency_ms: int = 0

    @property
    def category(self) -> str:
        """The id prefix (e.g. ``prc_001`` → ``prc``) — groups pricing/security/… in reports."""
        return self.id.split("_", 1)[0] if "_" in self.id else self.id


@dataclass
class RunResult:
    config: EvalConfig
    generated_at: datetime
    cases: list[CaseResult]

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def score(self) -> float:
        """Pass rate in [0, 1]."""
        return (self.passed / self.total) if self.total else 0.0

    @property
    def avg_latency_ms(self) -> int:
        return round(sum(c.latency_ms for c in self.cases) / self.total) if self.total else 0

    def by_category(self) -> dict[str, tuple[int, int]]:
        """category → (passed, total), for the per-topic breakdown."""
        out: dict[str, tuple[int, int]] = {}
        for case in self.cases:
            passed, total = out.get(case.category, (0, 0))
            out[case.category] = (passed + (1 if case.passed else 0), total + 1)
        return dict(sorted(out.items()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.as_dict(),
            "generated_at": self.generated_at.isoformat(),
            "score": round(self.score, 4),
            "passed": self.passed,
            "total": self.total,
            "avg_latency_ms": self.avg_latency_ms,
            "cases": [
                {
                    "id": c.id,
                    "passed": c.passed,
                    "failures": c.failures,
                    "routed_intent": c.routed_intent,
                    "actions": c.actions,
                    "latency_ms": c.latency_ms,
                    "text": c.text,
                }
                for c in self.cases
            ],
        }


def rank(runs: list[RunResult]) -> list[RunResult]:
    """Best first: highest pass rate, then fastest average latency as the tiebreak."""
    return sorted(runs, key=lambda r: (-r.score, r.avg_latency_ms, r.config.name))
