import httpx


async def test_healthz_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
    # Public probe stays minimal — env/build are admin-gated, not here.
    assert "env" not in body and "build" not in body
    # The request-context middleware stamps every response.
    assert resp.headers["X-Request-ID"].startswith("rid_")
