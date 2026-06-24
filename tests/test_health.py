"""Health & root discovery smoke tests.

Maps 1-to-1 to the three scenarios in
`openspec/changes/backend-pytest-smoke-suite/specs/backend-smoke-suite/req-smoke-health-001`:

1. `test_health_endpoint_returns_ok` — `GET /health` → 200 + the
   documented body.
2. `test_root_endpoint_exposes_discovery` — `GET /` → 200 + the
   documented discovery keys.
3. `test_fixtures_are_importable` — sanity check that the three core
   fixtures (`client`, `dev_jwt_admin`, `db_session`) resolve without
   raising. Acts as a conftest-refactor regression net.

These three tests do NOT touch the database. The `migrate` autouse
fixture in `conftest.py` ensures `mobbit_test` is migrated to head
before any test session, but none of these scenarios issue queries.
"""
from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings


async def test_health_endpoint_returns_ok(client: AsyncClient) -> None:
    """Scenario: `GET /health` returns 200 with the documented body."""
    resp = await client.get("/health")
    assert resp.status_code == 200, f"unexpected status: {resp.status_code} body={resp.text!r}"
    assert resp.headers["content-type"].startswith("application/json"), (
        f"unexpected content-type: {resp.headers.get('content-type')!r}"
    )
    body = resp.json()
    assert body == {
        "status": "ok",
        "service": settings.app_name,
        "env": settings.app_env,
    }, f"unexpected body: {body!r}"


async def test_root_endpoint_exposes_discovery(client: AsyncClient) -> None:
    """Scenario: `GET /` returns 200 with discovery keys."""
    resp = await client.get("/")
    assert resp.status_code == 200, f"unexpected status: {resp.status_code} body={resp.text!r}"
    body = resp.json()

    # All required keys are present.
    required = {
        "service",
        "version",
        "docs",
        "b2c_prefix",
        "admin_prefix",
        "provider_prefix",
        "webhooks_prefix",
    }
    missing = required - set(body.keys())
    assert not missing, f"missing discovery keys: {sorted(missing)}"

    # Per-key value contracts.
    assert body["service"] == settings.app_name
    assert body["b2c_prefix"] == "/api/b2c"
    assert body["admin_prefix"] == "/api/admin"
    assert body["provider_prefix"] == "/api/provider"
    assert body["webhooks_prefix"] == "/webhooks"
    assert body["docs"] == "/docs"


async def test_fixtures_are_importable(
    client: AsyncClient,
    dev_jwt_admin: str,
    db_session: AsyncSession,
) -> None:
    """Scenario: Shared fixtures are importable (conftest-refactor safety net).

    The test body is essentially `pass`, but its mere existence forces
    pytest to resolve all three fixtures. Any future conftest refactor
    that breaks a fixture signature, factory, or scope will surface as
    a `pytest.FixtureLookupError` here — not as a silent cascade of
    later test failures.
    """
    assert isinstance(dev_jwt_admin, str) and len(dev_jwt_admin) > 0, (
        f"dev_jwt_admin should be a non-empty str, got {dev_jwt_admin!r}"
    )
    assert isinstance(client, AsyncClient), f"client should be AsyncClient, got {type(client)!r}"
    assert isinstance(db_session, AsyncSession), (
        f"db_session should be AsyncSession, got {type(db_session)!r}"
    )