"""Read-only model tools (contracts §5, ADR-016).

The model may only READ: search the approved public knowledge base, fetch an
approved canonical answer, or fetch the portal URL/reset guidance. There are no
side-effecting tools — writes happen only via typed endpoints the browser calls.

Each tool returns a JSON string for the model plus out-of-band metadata the
orchestrator stores on the assistant message (canonical_answer_id, sources) and
uses to resolve suggested actions (never minted by the model).
"""

import json
from dataclasses import dataclass, field

from app.agent.adapter import ToolSpec
from app.domain.canonical.repository import CanonicalAnswerRepository
from app.domain.conversations.models import Source
from app.domain.knowledge.search import KnowledgeSearch

SEARCH_KNOWLEDGE = ToolSpec(
    name="search_knowledge",
    description=(
        "Search Cadre's approved public knowledge base for relevant content to ground a "
        "factual answer about Cadre's services, industries, approach, or partners."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional category filters.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results to return (1-5).",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)

GET_CANONICAL_ANSWER = ToolSpec(
    name="get_canonical_answer",
    description=(
        "Fetch Cadre's approved canonical answer for a sensitive intent. ALWAYS use this "
        "for pricing, security/compliance, the AI Maturity Index, the client portal, case "
        "studies, and client-relationship questions — never answer those from memory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "description": (
                    "One of: pricing, data_security, ai_maturity_index, portal_access, "
                    "company_overview, service_overview, industry_fit, llm_selection, "
                    "case_study, strategy_call, unsupported. Use 'strategy_call' when the "
                    "visitor wants to book/schedule a call or be connected with a strategist "
                    "or sales."
                ),
            }
        },
        "required": ["intent"],
        "additionalProperties": False,
    },
)

GET_PORTAL_INFORMATION = ToolSpec(
    name="get_portal_information",
    description="Get the approved client portal URL and password-reset guidance.",
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
)

TOOL_SPECS: list[ToolSpec] = [SEARCH_KNOWLEDGE, GET_CANONICAL_ANSWER, GET_PORTAL_INFORMATION]


@dataclass
class ToolExecutionResult:
    output: str  # JSON string returned to the model as function_call_output
    canonical_answer_id: str | None = None
    sources: list[Source] = field(default_factory=list)
    suggested_action_ids: list[str] = field(default_factory=list)


class ToolRegistry:
    def __init__(
        self,
        knowledge_search: KnowledgeSearch,
        canonical_repo: CanonicalAnswerRepository,
        *,
        portal_url: str,
        portal_reset_instructions: str,
    ) -> None:
        self._knowledge = knowledge_search
        self._canonical = canonical_repo
        self._portal_url = portal_url
        self._portal_reset = portal_reset_instructions

    def specs(self) -> list[ToolSpec]:
        return TOOL_SPECS

    async def execute(self, name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        if name == "search_knowledge":
            return await self._search(arguments)
        if name == "get_canonical_answer":
            return await self._canonical_answer(arguments)
        if name == "get_portal_information":
            return self._portal_information()
        return ToolExecutionResult(output=json.dumps({"error": f"unknown tool: {name}"}))

    async def _search(self, arguments: dict[str, object]) -> ToolExecutionResult:
        query = str(arguments.get("query", ""))
        raw_categories = arguments.get("categories")
        categories = [str(c) for c in raw_categories] if isinstance(raw_categories, list) else None
        raw_max = arguments.get("max_results")
        max_results = int(raw_max) if isinstance(raw_max, int) else 5
        result = await self._knowledge.search(query, categories=categories, max_results=max_results)
        sources = [
            Source(source_id=hit.source_id, title=hit.title, display_url=hit.display_url)
            for hit in result.results
            if hit.source_id
        ]
        output = json.dumps(
            {
                "search_status": result.status,
                "results": [
                    {
                        "source_id": hit.source_id,
                        "title": hit.title,
                        "content": hit.content,
                        "score": hit.score,
                        "display_url": hit.display_url,
                    }
                    for hit in result.results
                ],
            }
        )
        return ToolExecutionResult(output=output, sources=sources)

    async def _canonical_answer(self, arguments: dict[str, object]) -> ToolExecutionResult:
        intent = str(arguments.get("intent", ""))
        match = await self._canonical.get_canonical_answer(intent)
        output = json.dumps(
            {
                "matched": match.matched,
                "content": match.content,
                "allowed_action_ids": match.allowed_action_ids,
                "disclaimer": match.disclaimer,
                "mandatory_escalation": match.mandatory_escalation,
            }
        )
        return ToolExecutionResult(
            output=output,
            canonical_answer_id=match.canonical_answer_id,
            suggested_action_ids=list(match.allowed_action_ids),
        )

    def _portal_information(self) -> ToolExecutionResult:
        output = json.dumps(
            {"portal_url": self._portal_url, "reset_instructions": self._portal_reset}
        )
        return ToolExecutionResult(output=output, suggested_action_ids=["portal_support"])
