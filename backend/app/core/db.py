"""MongoDB connection helpers.

The client is created once at startup (see app.main lifespan) and closed at
shutdown. `tz_aware=True` so BSON dates come back as timezone-aware UTC datetimes.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings


def create_mongo_client(uri: str | None = None) -> AsyncIOMotorClient[dict[str, Any]]:
    settings = get_settings()
    return AsyncIOMotorClient(uri or settings.mongo_uri.get_secret_value(), tz_aware=True)


def get_database(
    client: AsyncIOMotorClient[dict[str, Any]], name: str | None = None
) -> AsyncIOMotorDatabase[dict[str, Any]]:
    settings = get_settings()
    return client[name or settings.mongo_db_name]
