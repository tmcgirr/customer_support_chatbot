"""App-settings repository — the runtime model-provider toggle (single upsert doc)."""

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from app.core.config import get_settings
from app.domain.settings.models import MODEL_PROVIDER_ID, ModelProviderSetting, Provider

Collection = AsyncIOMotorCollection[dict[str, Any]]


async def ensure_indexes(collection: Collection) -> None:
    # Single-doc store keyed by _id (Mongo indexes _id automatically) — no secondary
    # index needed. Kept for wiring symmetry with the other domains' ensure_indexes.
    return None


class SettingsRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def get_active_provider(self) -> Provider:
        """The runtime-selected provider, or the config startup default when unset."""
        doc = await self._collection.find_one({"_id": MODEL_PROVIDER_ID})
        if doc is None:
            return get_settings().model_provider
        return ModelProviderSetting.model_validate(doc).active_provider

    async def set_active_provider(
        self, provider: Provider, *, updated_by: str
    ) -> ModelProviderSetting:
        setting = ModelProviderSetting(
            active_provider=provider,
            updated_by=updated_by,
            updated_at=datetime.now(UTC),
        )
        await self._collection.replace_one(
            {"_id": MODEL_PROVIDER_ID}, setting.model_dump(by_alias=True), upsert=True
        )
        return setting
