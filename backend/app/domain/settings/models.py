"""Runtime app settings (contracts §7).

A tiny single-document store so the API AND the separate worker process read the same
live value. Model configuration is otherwise env-only and promoted (invariants #14/#15);
the active model provider is the one runtime-switchable knob, gated in admin (admin role,
reason required, audited).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Provider = Literal["openai", "anthropic", "openrouter"]

# Fixed _id of the singleton model-provider setting document.
MODEL_PROVIDER_ID = "model_provider"


class ModelProviderSetting(BaseModel):
    """The runtime-selected chat provider. No secrets — only which configured provider
    is active, who set it, and when (provenance for the audit trail)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default=MODEL_PROVIDER_ID, alias="_id")
    active_provider: Provider
    updated_by: str
    updated_at: datetime
