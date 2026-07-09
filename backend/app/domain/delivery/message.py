"""Neutral outbound-message rendering for request delivery.

Every transport (simulated, webhook, email) formats a request through this ONE
function, so the mock preview shown in admin is exactly what a real destination
would receive. The output is provider-agnostic — each adapter serializes it for
its channel (Slack/Teams JSON, an email body, etc.). This module has no provider
types and never logs its output (it carries contact PII; invariant #5)."""

from dataclasses import dataclass, field

from app.domain.requests.models import RequestRecord

_TITLES = {
    "strategy_call": "New strategy-call request",
    "portal_support": "New portal-support request",
    "human_escalation": "Human escalation requested",
}


@dataclass(frozen=True)
class DeliveryMessage:
    title: str
    reference: str
    fields: list[tuple[str, str]] = field(default_factory=list)

    def to_text(self) -> str:
        """Plain-text rendering for an email body / Slack-Teams `text` payload."""
        lines = [self.title, ""]
        lines += [f"{label}: {value}" for label, value in self.fields if value]
        return "\n".join(lines)

    def as_dict(self) -> dict[str, str]:
        """Structured key→value (for a webhook JSON body or a CRM intake)."""
        return {label: value for label, value in self.fields if value}


def format_request(record: RequestRecord) -> DeliveryMessage:
    """Render a persisted request into a neutral delivery message. Includes the
    contact + the per-type ``fields`` the visitor submitted, plus the local
    reference/ids operators use to trace it (never provider ids)."""
    title = _TITLES.get(record.type, "New request")
    fields: list[tuple[str, str]] = [
        ("Reference", record.reference),
        ("Type", record.type),
        ("Name", record.contact.name or ""),
        ("Email", record.contact.email or ""),
        ("Company", record.contact.company or ""),
    ]
    # The per-type payload (reason/industry, issue_category/description, category/…).
    for key, value in record.fields.items():
        label = key.replace("_", " ").capitalize()
        fields.append((label, str(value)))
    fields.append(("Conversation", record.conversation_id))
    fields.append(("Submitted", record.created_at.isoformat()))
    return DeliveryMessage(
        title=f"{title} ({record.reference})", reference=record.reference, fields=fields
    )
