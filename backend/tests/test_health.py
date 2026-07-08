import httpx


async def test_healthz_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
    # The request-context middleware stamps every response.
    assert resp.headers["X-Request-ID"].startswith("rid_")
