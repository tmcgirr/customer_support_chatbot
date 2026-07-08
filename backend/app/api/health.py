"""Liveness endpoint for the walking skeleton and deploy checks."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/healthz", response_model=HealthResponse, tags=["health"])
async def healthz() -> HealthResponse:
    # Minimal public liveness probe. Environment/build details are operational
    # and live behind admin auth (GET /api/v1/admin/system), not on this public
    # endpoint, so an unauthenticated caller can't fingerprint env or build.
    return HealthResponse(status="ok", version=get_settings().app_version)
