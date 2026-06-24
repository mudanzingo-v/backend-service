"""Admin router auth boundary + pagination contract smoke tests.

Maps 1-to-1 to the five scenarios in
`openspec/changes/backend-pytest-smoke-suite/specs/backend-smoke-suite/req-smoke-admin-router-001`:

1. `test_admin_endpoint_without_token_returns_401` — no `Authorization`
   header → 401 (per spec scenario 1).
2. `test_admin_endpoint_with_malformed_token_returns_401` —
   `Authorization: Bearer not-a-jwt` → 401 (per spec scenario 2).
3. `test_admin_endpoint_with_dev_jwt_admin_returns_200` — valid
   `dev_jwt_admin` token → 200 (per spec scenario 3; the happy path).
4. `test_set_pagination_headers_writes_all_four` — pure unit test on
   `app.core.pagination.set_pagination_headers` (per spec scenario 4).
5. `test_list_quotations_returns_pagination_headers` — integration test
   against `GET /api/admin/quotation?limit=5&offset=0` (per spec
   scenario 5).

The auth-safety-guard test (per `req-auth-safety-001`) lives in
`test_auth_dev_mode.py`.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Response
from httpx import AsyncClient

from app.core.pagination import set_pagination_headers


def test_set_pagination_headers_writes_all_four() -> None:
    """Scenario: `set_pagination_headers` writes all four headers (unit test).

    Per `req-smoke-admin-router-001` scenario 4. Pure Python — no HTTP,
    no DB. Verifies both the happy path (`X-Has-Next="true"`) and the
    boundary case (`X-Has-Next="false"` when `offset + limit >= total`).
    """
    response = Response()

    # First call: 20 + 10 < 42 → X-Has-Next must be "true".
    set_pagination_headers(response, total=42, limit=10, offset=20)
    assert response.headers["X-Total-Count"] == "42", (
        f"X-Total-Count should be '42', got {response.headers.get('X-Total-Count')!r}"
    )
    assert response.headers["X-Limit"] == "10", (
        f"X-Limit should be '10', got {response.headers.get('X-Limit')!r}"
    )
    assert response.headers["X-Offset"] == "20", (
        f"X-Offset should be '20', got {response.headers.get('X-Offset')!r}"
    )
    assert response.headers["X-Has-Next"] == "true", (
        f"X-Has-Next should be 'true' (20+10<42), got {response.headers.get('X-Has-Next')!r}"
    )

    # Second call: 40 + 10 >= 42 → X-Has-Next must be "false".
    set_pagination_headers(response, total=42, limit=10, offset=40)
    assert response.headers["X-Has-Next"] == "false", (
        f"X-Has-Next should be 'false' (40+10>=42), got {response.headers.get('X-Has-Next')!r}"
    )


async def test_list_quotations_returns_pagination_headers(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """Scenario: `GET /api/admin/quotation` emits pagination headers over HTTP.

    Per `req-smoke-admin-router-001` scenario 5. Integration test —
    exercises the full HTTP stack (auth → dep → DB → pagination
    helper) in one shot. A freshly-migrated `mobbit_test` may
    legitimately have `X-Total-Count=0` (the endpoint filters out
    synthetic records), so we only assert `>= 0`.
    """
    resp = await client.get(
        "/api/admin/quotation?limit=5&offset=0",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200, f"unexpected status: {resp.status_code} body={resp.text!r}"

    # All four documented headers must be present.
    for header in ("X-Total-Count", "X-Limit", "X-Offset", "X-Has-Next"):
        assert header in resp.headers, (
            f"missing pagination header {header!r}; headers={dict(resp.headers)}"
        )

    # Per-header value contracts.
    assert resp.headers["X-Limit"] == "5", (
        f"X-Limit should be '5', got {resp.headers.get('X-Limit')!r}"
    )
    assert resp.headers["X-Offset"] == "0", (
        f"X-Offset should be '0', got {resp.headers.get('X-Offset')!r}"
    )
    total = int(resp.headers["X-Total-Count"])
    assert total >= 0, f"X-Total-Count should be int >= 0, got {total}"
    assert resp.headers["X-Has-Next"] in ("true", "false"), (
        f"X-Has-Next should be a boolean string, got {resp.headers.get('X-Has-Next')!r}"
    )

    # Body must be a list (paginated helper does not change the response
    # shape; pagination is communicated via headers).
    body = resp.json()
    assert isinstance(body, list), (
        f"response body should be a list, got {type(body).__name__}: {body!r}"
    )
    # Body length must respect the limit.
    assert len(body) <= 5, f"body length {len(body)} exceeds limit=5"


async def test_admin_endpoint_without_token_returns_401(client: AsyncClient) -> None:
    """Scenario: Missing bearer token is rejected with 401.

    Per `req-smoke-admin-router-001` scenario 1.
    """
    resp = await client.get("/api/admin/quotation")  # no Authorization header
    assert resp.status_code == 401, (
        f"missing-token request should return 401; got status={resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert isinstance(body, dict), f"body should be a dict, got {type(body).__name__}: {body!r}"
    assert "message" in body, f"body should have a 'message' key, got: {body!r}"


async def test_admin_endpoint_with_malformed_token_returns_401(
    client: AsyncClient,
) -> None:
    """Scenario: Malformed bearer token is rejected with 401.

    Per `req-smoke-admin-router-001` scenario 2. The token `not-a-jwt`
    is not a parseable JWT, so the auth module raises
    `UnauthorizedError("Invalid token header: …")` and the response
    body MUST contain a `message` key referencing the token header.
    """
    resp = await client.get(
        "/api/admin/quotation",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401, (
        f"malformed-token request should return 401; got "
        f"status={resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert isinstance(body, dict), f"body should be a dict, got {type(body).__name__}: {body!r}"
    assert "message" in body, f"body should have a 'message' key, got: {body!r}"
    # The auth module raises UnauthorizedError("Invalid token header: …")
    # when `jwt.get_unverified_header` fails to parse the token.
    assert "Invalid token" in body["message"], (
        f"message should reference 'Invalid token'; got: {body.get('message')!r}"
    )


async def test_admin_endpoint_with_dev_jwt_admin_returns_200(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """Scenario: Dev-mode JWT for the admin pool authenticates successfully.

    Per `req-smoke-admin-router-001` scenario 3. The happy path —
    proves the dev-mode auth flow works end-to-end. A freshly-migrated
    `mobbit_test` may legitimately have an empty body (`[]`).
    """
    resp = await client.get(
        "/api/admin/quotation",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200, (
        f"valid dev-jwt_admin request should return 200; got "
        f"status={resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert isinstance(body, list), (
        f"response body should be a list, got {type(body).__name__}: {body!r}"
    )
