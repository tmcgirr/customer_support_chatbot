import os

# The test suite always runs as dev. Set this BEFORE importing app (which builds
# Settings at import): env now defaults to "prod", whose secret guard would
# otherwise reject the in-repo default secrets used in tests.
os.environ["ENV"] = "dev"

import httpx  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
async def client() -> "httpx.AsyncClient":
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
        yield ac
