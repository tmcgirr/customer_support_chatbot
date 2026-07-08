"""Seed the canonical_answers collection with the approved wording (docs 05 §3).

Idempotent: keyed by intent, so re-running updates records in place rather than
creating duplicates. Every record is stored ``approved`` so
``get_canonical_answer`` can serve it (CLAUDE.md invariant #8). Wording is
verbatim from docs/05_Conversation_and_Content_Specification.md §3 — never
invent prices, client names, certifications, or AI Maturity methodology
(§7 prohibited claims).

    uv run python scripts/seed_canonical.py
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

# Allow direct execution (`uv run python scripts/seed_canonical.py`): Python only
# puts this file's directory on sys.path, so add the backend root for `app`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import ids  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.domain.canonical.models import CanonicalAnswer  # noqa: E402
from app.domain.canonical.repository import (  # noqa: E402
    CanonicalAnswerRepository,
    ensure_indexes,
)

# Verbatim approved wording from docs 05 §3. ``allowed_action_ids`` are IDs the
# application resolves into workflows/prompts (the model cannot mint actions);
# ``mandatory_escalation`` follows §3's explicit escalation instructions.
SEED_ANSWERS: list[dict[str, Any]] = [
    {
        "name": "Company overview",
        "intent": "company_overview",
        "owner": "Marketing, service owners",
        "content": (
            "Cadre AI is an AI strategy and implementation consultancy. We help "
            "businesses move from AI confusion to AI confidence — going department "
            "by department to identify high-ROI AI opportunities, build practical "
            "workflows and agents, and train teams so the changes actually stick.\n\n"
            "Cadre's core services are AI Strategy, AI Leadership & Facilitation, "
            "AI Engineering, and AI Agents."
        ),
        "allowed_action_ids": ["strategy_call"],
        "mandatory_escalation": False,
    },
    {
        "name": "Service overview",
        "intent": "service_overview",
        "owner": "Marketing, service owners",
        "content": (
            "- **AI Strategy:** identify and prioritize valuable AI opportunities, "
            "understand readiness and constraints, and build a practical roadmap.\n"
            "- **AI Leadership & Facilitation:** align leadership teams around AI "
            "priorities, operating models, governance, and adoption.\n"
            "- **AI Engineering:** design and build production AI workflows, "
            "applications, and integrations.\n"
            "- **AI Agents:** systems that perform defined tasks, use tools, and "
            "support business workflows with appropriate controls and oversight."
        ),
        "allowed_action_ids": ["service_discovery", "strategy_call"],
        "mandatory_escalation": False,
    },
    {
        "name": "Industry fit",
        "intent": "industry_fit",
        "owner": "Marketing, service owners",
        "content": (
            "Cadre works with B2B organizations including professional services, "
            "private equity and PE-backed companies, financial services, real "
            "estate, construction, manufacturing, and retail.\n\n"
            "The best fit depends less on the industry label and more on the "
            "workflows, decisions, and operational problems you want to improve."
        ),
        "allowed_action_ids": ["service_discovery", "strategy_call"],
        "mandatory_escalation": False,
    },
    {
        "name": "AI Maturity Index",
        "intent": "ai_maturity_index",
        "owner": "Product owner",
        "content": (
            "The AI Maturity Index is Cadre's assessment of how prepared an "
            "organization is to adopt and scale AI effectively. It helps leaders "
            "understand current capabilities, gaps, and likely priorities.\n\n"
            "To receive a score, you can request an assessment or speak with a "
            "Cadre strategist about the process."
        ),
        "allowed_action_ids": ["strategy_call"],
        "mandatory_escalation": False,
    },
    {
        "name": "LLM selection and partners",
        "intent": "llm_selection",
        "owner": "AI Engineering",
        "content": (
            "Cadre doesn't use one model for every situation. Selection depends on "
            "the use case, answer quality, latency, cost, context requirements, "
            "integration needs, deployment constraints, and data-handling "
            "requirements.\n\n"
            "Cadre works across providers and platforms including OpenAI, "
            "Anthropic (Claude), Google, Microsoft, AWS, Salesforce, and Snowflake, "
            "and uses OpenRouter for flexible model access. A final recommendation "
            "normally requires understanding your workflow and security "
            "requirements."
        ),
        "allowed_action_ids": ["strategy_call"],
        "mandatory_escalation": False,
    },
    {
        "name": "Data security",
        "intent": "data_security",
        "owner": "Security/Legal",
        "content": (
            "Cadre evaluates data security as part of the design of each AI "
            "solution: what information is sent to a model, who can access the "
            "system, provider data-handling terms, retention, logging, encryption, "
            "and deployment requirements.\n\n"
            "The correct approach depends on your systems, data sensitivity, and "
            "regulatory obligations. For a security review or organization-specific "
            "requirements, I can connect you with the appropriate Cadre team."
        ),
        # §3: certifications, compliance, contractual commitments, residency, and
        # client-specific architecture must escalate — never answered inline.
        "allowed_action_ids": ["human_escalation"],
        "mandatory_escalation": True,
    },
    {
        "name": "Pricing",
        "intent": "pricing",
        "owner": "Sales/Leadership",
        "content": (
            "Cadre engagements are scoped to the business problem: number of "
            "workflows, systems involved, data requirements, implementation "
            "complexity, and level of organizational support required.\n\n"
            "I don't have an approved fixed price for that, but I can help you "
            "request a conversation with a strategist."
        ),
        "allowed_action_ids": ["strategy_call"],
        "mandatory_escalation": False,
    },
    {
        "name": "Case studies",
        "intent": "case_study",
        "owner": "Marketing/Client owner",
        "content": (
            "I can't share specific client names or results in this chat. Cadre "
            "can walk through relevant, approved examples for your industry on a "
            "strategy call."
        ),
        "allowed_action_ids": ["strategy_call"],
        "mandatory_escalation": False,
    },
    {
        "name": "Client portal",
        "intent": "portal_access",
        "owner": "Client Success",
        # [PORTAL URL] stays a placeholder: the approved URL is supplied at answer
        # time by the get_portal_information tool from configuration (contracts §5).
        "content": (
            "Cadre clients can use the client portal to track their AI tools, "
            "agents, and results. You can access it here: **[PORTAL URL]**.\n\n"
            "If you can't sign in, I can help you submit an access-support request. "
            "For security, I can't inspect or verify private account information "
            "from this public chat."
        ),
        "allowed_action_ids": ["portal_access", "portal_support"],
        "mandatory_escalation": False,
    },
    {
        "name": "Unsupported question",
        "intent": "unsupported",
        "owner": "Product + Engineering",
        "content": (
            "I don't have enough approved information to answer that reliably. I "
            "can send your question and the relevant context from this conversation "
            "to the appropriate Cadre team."
        ),
        "allowed_action_ids": ["human_escalation"],
        "mandatory_escalation": False,
    },
]


def build_answers(now: datetime) -> list[CanonicalAnswer]:
    """Materialize the seed dicts into approved ``CanonicalAnswer`` records."""
    review = now + timedelta(days=180)
    return [
        CanonicalAnswer(
            id=ids.canonical_answer_id(),
            name=entry["name"],
            intent=entry["intent"],
            audience="public",
            content=entry["content"],
            disclaimer=entry.get("disclaimer"),
            allowed_action_ids=entry.get("allowed_action_ids", []),
            mandatory_escalation=entry.get("mandatory_escalation", False),
            status="approved",
            version=1,
            owner=entry["owner"],
            effective_date=now,
            review_date=review,
        )
        for entry in SEED_ANSWERS
    ]


async def seed() -> int:
    """Upsert every canonical answer; return the number seeded."""
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    try:
        collection = client[get_settings().mongo_db_name]["canonical_answers"]
        await ensure_indexes(collection)
        repository = CanonicalAnswerRepository(collection)
        answers = build_answers(datetime.now(UTC))
        for answer in answers:
            await repository.upsert(answer)
        return len(answers)
    finally:
        client.close()


def main() -> None:
    count = asyncio.run(seed())
    print(f"Seeded {count} canonical answers.")


if __name__ == "__main__":
    main()
