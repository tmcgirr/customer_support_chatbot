"""Canonical answer document + tool-result models (contracts §7, §5).

Canonical answers hold the *approved* wording for the questions the assistant is
never allowed to improvise: pricing, security, the AI Maturity Index, the client
portal, case studies, and client-relationship questions (CLAUDE.md invariant #8).
The model reaches them read-only through ``get_canonical_answer``; the
application — not the model — resolves any ``allowed_action_ids`` into workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CanonicalStatus = Literal["draft", "approved"]


class CanonicalAnswer(BaseModel):
    # populate_by_name lets us construct with `id=` while Mongo stores `_id`.
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    name: str
    intent: str
    audience: Literal["public"] = "public"
    content: str
    disclaimer: str | None = None
    allowed_action_ids: list[str] = Field(default_factory=list)
    mandatory_escalation: bool = False
    status: CanonicalStatus = "draft"
    version: int = 1
    owner: str
    effective_date: datetime
    review_date: datetime


@dataclass(frozen=True)
class CanonicalMatch:
    """Result of the ``get_canonical_answer`` model tool (contracts §5).

    ``matched`` is ``False`` when no *approved* record exists for the intent, so
    the caller falls back to retrieval or escalation instead of exposing
    unapproved wording.
    """

    matched: bool
    canonical_answer_id: str | None
    content: str | None
    allowed_action_ids: list[str]
    disclaimer: str | None
    mandatory_escalation: bool

    @classmethod
    def unmatched(cls) -> CanonicalMatch:
        return cls(
            matched=False,
            canonical_answer_id=None,
            content=None,
            allowed_action_ids=[],
            disclaimer=None,
            mandatory_escalation=False,
        )

    @classmethod
    def from_answer(cls, answer: CanonicalAnswer) -> CanonicalMatch:
        return cls(
            matched=True,
            canonical_answer_id=answer.id,
            content=answer.content,
            allowed_action_ids=list(answer.allowed_action_ids),
            disclaimer=answer.disclaimer,
            mandatory_escalation=answer.mandatory_escalation,
        )
