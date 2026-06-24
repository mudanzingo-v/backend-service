"""OpenAPI schema + B2C reachability smoke tests.

Maps 1-to-1 to the scenarios in:

- `openspec/changes/backend-pytest-smoke-suite/specs/backend-smoke-suite/req-smoke-openapi-001`
  (4 scenarios)
- `openspec/changes/backend-pytest-smoke-suite/specs/backend-smoke-suite/req-smoke-b2c-router-001`
  (2 scenarios; both live in this file per spec — the B2C path
  presence is folded into `test_openapi_lists_admin_provider_webhooks_and_b2c_paths`
  and the B2C reachability is a new `test_get_b2c_products_returns_200_without_auth`)

These tests are pure HTTP smoke; no DB writes. The `migrate` autouse
fixture in `conftest.py` still runs once per session (so the B2C
catalog table exists for the reachability test) but none of these
scenarios issue queries.
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_openapi_json_returns_200_with_schema(client: AsyncClient) -> None:
    """Scenario: `/openapi.json` returns the documented schema metadata.

    Per `req-smoke-openapi-001` scenario 1.
    """
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200, f"unexpected status: {resp.status_code} body={resp.text!r}"
    assert resp.headers["content-type"].startswith("application/json"), (
        f"unexpected content-type: {resp.headers.get('content-type')!r}"
    )
    body = resp.json()
    assert isinstance(body, dict), f"openapi body should be a dict, got {type(body)!r}"
    assert "info" in body, f"openapi body missing 'info' key: keys={sorted(body.keys())}"
    assert "paths" in body, f"openapi body missing 'paths' key: keys={sorted(body.keys())}"
    assert body["info"]["title"] == "Mobbit Backend Service", (
        f"unexpected info.title: {body['info'].get('title')!r}"
    )
    assert body["info"]["version"] == "0.1.0", (
        f"unexpected info.version: {body['info'].get('version')!r}"
    )


async def test_openapi_lists_admin_provider_webhooks_and_b2c_paths(
    client: AsyncClient,
) -> None:
    """Scenario: Admin, provider, webhooks, and B2C paths are registered.

    Per `req-smoke-openapi-001` scenario 2 (admin, provider, webhooks)
    + `req-smoke-b2c-router-001` scenario 1 (B2C). Folded into a single
    test to keep the file at 5 tests (matches the spec's
    "5 scenarios in this file" count). All four prefixes are asserted
    against the same `paths` dict.
    """
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200, f"unexpected status: {resp.status_code} body={resp.text!r}"
    paths = resp.json()["paths"]
    assert isinstance(paths, dict), f"paths should be a dict, got {type(paths)!r}"

    # At least one path starting with each prefix.
    admin_paths = [p for p in paths if p.startswith("/api/admin")]
    provider_paths = [p for p in paths if p.startswith("/api/provider")]
    webhooks_paths = [p for p in paths if p.startswith("/webhooks")]
    b2c_paths = [p for p in paths if p.startswith("/api/b2c")]

    assert admin_paths, f"no paths under /api/admin; got: {sorted(paths.keys())[:5]} ..."
    assert provider_paths, f"no paths under /api/provider; got: {sorted(paths.keys())[:5]} ..."
    assert webhooks_paths, f"no paths under /webhooks; got: {sorted(paths.keys())[:5]} ..."
    assert b2c_paths, f"no paths under /api/b2c; got: {sorted(paths.keys())[:5]} ..."


async def test_docs_endpoint_serves_html(client: AsyncClient) -> None:
    """Scenario: `/docs` serves the Swagger UI HTML.

    Per `req-smoke-openapi-001` scenario 3.
    """
    resp = await client.get("/docs")
    assert resp.status_code == 200, f"unexpected status: {resp.status_code} body={resp.text!r}"
    assert resp.headers["content-type"].startswith("text/html"), (
        f"unexpected content-type: {resp.headers.get('content-type')!r}"
    )


async def test_redoc_endpoint_serves_html(client: AsyncClient) -> None:
    """Scenario: `/redoc` serves the ReDoc UI HTML.

    Per `req-smoke-openapi-001` scenario 4.
    """
    resp = await client.get("/redoc")
    assert resp.status_code == 200, f"unexpected status: {resp.status_code} body={resp.text!r}"
    assert resp.headers["content-type"].startswith("text/html"), (
        f"unexpected content-type: {resp.headers.get('content-type')!r}"
    )


async def test_get_b2c_products_returns_200_without_auth(client: AsyncClient) -> None:
    """Scenario: `GET /api/b2c/products` returns 200 without auth.

    Per `req-smoke-b2c-router-001` scenario 2. The B2C catalog is
    public; no `Authorization` header is sent. This validates the
    public-reachability contract: a future change that accidentally
    adds an `auth_required` dependency to `/api/b2c/products` will
    fail this test with a clear 401 response.
    """
    # NOTE: no Authorization header.
    resp = await client.get("/api/b2c/products")
    assert resp.status_code == 200, (
        f"B2C products endpoint should be publicly reachable; got "
        f"status={resp.status_code} body={resp.text!r}"
    )
    assert resp.headers["content-type"].startswith("application/json"), (
        f"unexpected content-type: {resp.headers.get('content-type')!r}"
    )
    body = resp.json()
    assert isinstance(body, list), (
        f"B2C products body should be a JSON list; got {type(body).__name__}: {body!r}"
    )
