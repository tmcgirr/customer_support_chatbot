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
    return HealthResponse(status="ok", version=get_settings().app_version)
