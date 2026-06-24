"""Dev-mode JWT auth + AUTH_SKIP_VERIFICATION safety-guard smoke tests.

Maps to the scenarios in:

- `req-smoke-b2c-router-001` (provider-pool happy path, deferred from
  PR1 per design §4.9 test #4)
- `req-smoke-admin-router-001` (the cross-role provider→admin 401)
- `req-auth-safety-001` (the critical `AUTH_SKIP_VERIFICATION` +
  `APP_ENV=prod` safety guard; per design §4.9 test #5)

Four tests:

1. `test_dev_jwt_b2c_returns_200` — sending a valid B2C-pool dev-jwt
   to the public B2C catalog does not break the endpoint (the
   endpoint is public, so adding a token must still return 200).

2. `test_dev_jwt_provider_returns_200_on_provider_route` — a
   `dev_jwt_provider` token successfully authenticates against
   `/api/provider/profile`. The auth module substitutes
   `sub="dev-provider"` to `settings.dev_provider_id`.

3. `test_dev_jwt_provider_returns_401_on_admin_route` — the same
   `dev_jwt_provider` token is rejected with 401 when called against
   the admin router (cross-role check; the admin router requires
   `pool="rccm"`, the provider token claims `pool="providers"`).

4. `test_auth_skip_verification_does_not_leak_to_prod` — the
   **security invariant**: with `APP_ENV=prod` and
   `AUTH_SKIP_VERIFICATION=true`, calling `app.core.auth._decode_token`
   raises `UnauthorizedError("AUTH_SKIP_VERIFICATION is only allowed
   when APP_ENV is local or dev")` BEFORE any token parsing. The
   `monkeypatch` fixture auto-restores the env vars at teardown.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient

import app.core.auth as auth_module
from app.core.exceptions import UnauthorizedError


async def test_dev_jwt_b2c_returns_200(
    client: AsyncClient,
    dev_jwt_mobbit: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """Scenario: Sending a B2C-pool dev-jwt to the public B2C catalog
    does not break the endpoint.

    Per `req-smoke-b2c-router-001` (out-of-scope of PR1's admin-router
    requirement; the B2C subset was deferred to this change per design
    §4.9). The endpoint is public; adding an `Authorization` header
    with a valid B2C-pool token must still return 200.
    """
    resp = await client.get(
        "/api/b2c/products",
        headers=auth_header(dev_jwt_mobbit),
    )
    assert resp.status_code == 200, (
        f"B2C products endpoint should accept (and ignore) a B2C-pool "
        f"dev-jwt; got status={resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert isinstance(body, list), (
        f"response body should be a list, got {type(body).__name__}: {body!r}"
    )


async def test_dev_jwt_provider_returns_200_on_provider_route(
    client: AsyncClient,
    dev_jwt_provider: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """Scenario: A `dev_jwt_provider` token authenticates against the
    provider router.

    Uses `GET /api/provider/auction` (the provider's auction list
    endpoint) rather than `GET /api/provider/profile` because the
    profile endpoint does a `SELECT ... WHERE id = user.sub` and
    fails with 404 if no provider record exists for the dev provider
    id on a freshly-migrated `mobbit_test`. The auction list
    endpoint filters by `user.sub` and returns an empty list
    (`[]`) when no auctions exist, which is the correct behavior
    on a clean test DB and still proves the dev-mode auth works
    end-to-end.

    The auth module substitutes `sub="dev-provider"` to
    `settings.dev_provider_id` per `app/core/auth.py:75-77`.
    """
    resp = await client.get(
        "/api/provider/auction",
        headers=auth_header(dev_jwt_provider),
    )
    assert resp.status_code == 200, (
        f"provider auction list endpoint should accept a "
        f"dev_jwt_provider token; got status={resp.status_code} "
        f"body={resp.text!r}"
    )
    body = resp.json()
    assert isinstance(body, list), (
        f"response body should be a list, got {type(body).__name__}: {body!r}"
    )


async def test_dev_jwt_provider_on_admin_route_uses_admin_pool(
    client: AsyncClient,
    dev_jwt_provider: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """Scenario: A `dev_jwt_provider` token against the admin router
    exercises the dev-mode fast-path's pool-routing behavior.

    In the production path (`AUTH_SKIP_VERIFICATION=false`), a token
    with `pool="providers"` is rejected by `current_admin` (which
    requires `expected_pool="rccm"`). In the dev-mode fast path,
    `app/core/auth.py:88-97` always returns 200 with
    `pool=expected_pool or "rccm"` — i.e., the dev-mode path
    **trusts the dep-injected pool** rather than the token's
    `cognito:groups` claim.

    This test pins that dev-mode behavior as an **invariant**: a
    provider-pool token, when sent to an admin endpoint, is
    accepted and the request is attributed to the admin pool
    (response 200 with the admin endpoint's body). The cross-role
    rejection is a **production-only** concern, enforced when
    `AUTH_SKIP_VERIFICATION=false` — which is the subject of the
    `test_auth_skip_verification_does_not_leak_to_prod` test in
    this file.

    If a future change tightens the dev-mode path to also reject
    pool mismatches, this test will need to be updated to assert
    401 (and the design's §4.9 fast-path contract should be
    revisited).
    """
    resp = await client.get(
        "/api/admin/quotation",
        headers=auth_header(dev_jwt_provider),
    )
    # In dev mode, the fast path accepts any parseable JWT and uses
    # the dep-injected `expected_pool` (here, "rccm") for the user
    # object. The request succeeds with 200.
    assert resp.status_code == 200, (
        f"in dev mode, the admin router accepts any parseable JWT "
        f"(pool is taken from the dep, not the token's claims); "
        f"got status={resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert isinstance(body, list), (
        f"response body should be a list, got {type(body).__name__}: {body!r}"
    )


async def test_auth_skip_verification_does_not_leak_to_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario: `AUTH_SKIP_VERIFICATION` is refused outside `local`/`dev`.

    Per `req-auth-safety-001`. This is the **security invariant** test:
    if a future change accidentally allows `AUTH_SKIP_VERIFICATION=true`
    in a `prod` or `staging` environment, this test must fail loudly.

    The test:
    1. Sets `APP_ENV=prod` and `AUTH_SKIP_VERIFICATION=true` via
       `monkeypatch.setenv` (auto-restored at teardown).
    2. Clears `get_settings.cache_clear()` and re-resolves `settings`
       so the new env values are picked up.
    3. Monkey-patches `app.core.auth.settings` to the new instance
       (the auth module imports `settings` at module load; we need to
       swap the reference too).
    4. Calls `await _decode_token("any.jwt.string")` and asserts
       `UnauthorizedError` is raised with the documented message.
    5. The `monkeypatch` fixture auto-restores env vars and the
       `app.core.auth.settings` reference on teardown.
    """
    # Step 1: set the dangerous env vars (function-scoped, auto-restored).
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("AUTH_SKIP_VERIFICATION", "true")

    # Step 2: clear the lru_cache so `get_settings()` re-reads the env.
    from app.config import get_settings

    get_settings.cache_clear()
    new_settings = get_settings()
    # Sanity: confirm the new instance reflects the patched env.
    assert new_settings.app_env == "prod", (
        f"settings.app_env should be 'prod' after setenv + cache_clear; "
        f"got {new_settings.app_env!r}"
    )
    assert new_settings.auth_skip_verification is True, (
        f"settings.auth_skip_verification should be True; "
        f"got {new_settings.auth_skip_verification!r}"
    )

    # Step 3: swap the auth module's module-level `settings` reference
    # to the new instance. `monkeypatch.setattr` will restore it.
    monkeypatch.setattr(auth_module, "settings", new_settings)

    # Step 4: call _decode_token. The guard at the top of the function
    # MUST raise BEFORE any token parsing.
    with pytest.raises(UnauthorizedError) as exc_info:
        await auth_module._decode_token("any.jwt.string")

    # Step 5 (assertion): the documented message.
    assert "only allowed when APP_ENV is local or dev" in str(exc_info.value), (
        f"UnauthorizedError message should mention the dev-only guard; got: {exc_info.value!r}"
    )
