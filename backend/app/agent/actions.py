"""Application-owned suggested-action allowlist (ADR-016).

The model may only emit action IDs; the application resolves them to
``{id, label}`` objects. IDs the model invents fall back to a humanized label but
are never trusted for behavior. Phase 3 wires canonical ``allowed_action_ids``
through here.
"""

ACTION_LABELS: dict[str, str] = {
    "company_overview": "What does Cadre AI do?",
    "industry_fit": "Do you work with my industry?",
    "service_discovery": "Which service is right for us?",
    "ai_maturity_index": "What is the AI Maturity Index?",
    "strategy_call": "Book a strategy call",
    "portal_access": "Access the client portal",
    "portal_support": "Get portal support",
    "human_escalation": "Talk to a person",
}


def resolve_actions(action_ids: list[str]) -> list[dict[str, str]]:
    return [
        {
            "id": action_id,
            "label": ACTION_LABELS.get(action_id, action_id.replace("_", " ").title()),
        }
        for action_id in action_ids
    ]
