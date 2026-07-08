import httpx
import pytest
from httpx import ASGITransport

from app.main import app


@pytest.fixture
async def client() -> "httpx.AsyncClient":
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
        yield ac
