"""
Auth unit tests — dev-mode paths, FastAPI deps, and helper functions.

Covers the uncovered lines in `app/core/auth.py`:

- `_decode_token` error paths (invalid token, missing kid)
- Dev-mode sub substitution (dev-provider → dev_provider_id)
- `current_user` / `current_provider` / `current_admin` with no creds
- `_cognito_client_for` helper
- `Settings.cognito_client_for` monkey-patch
"""
from __future__ import annotations

import pytest
from jose import jwt

# Module under test
import app.core.auth as auth_module
from app.config import settings
from app.core.exceptions import UnauthorizedError

# =============================================================================
# _decode_token — error paths
# =============================================================================

async def test_decode_token_with_garbage_raises_unauthorized() -> None:
    """`_decode_token` with a non-JWT string raises UnauthorizedError."""
    with pytest.raises(UnauthorizedError) as exc_info:
        await auth_module._decode_token("not-a-jwt-at-all")
    assert "Invalid token" in str(exc_info.value)


async def test_decode_token_missing_kid_raises_unauthorized() -> None:
    """
    `_decode_token` raises UnauthorizedError when the JWT header has no `kid`.

    `make_dev_jwt` always adds `kid="dev-kid"`, so we craft a token manually
    without the `headers` kwarg to omit `kid`.
    """
    token = jwt.encode({"sub": "test"}, key="", algorithm="HS256")
    with pytest.raises(UnauthorizedError) as exc_info:
        await auth_module._decode_token(token)
    assert "missing 'kid'" in str(exc_info.value)


async def test_decode_token_invalid_claims_raises_unauthorized() -> None:
    """
    `_decode_token` with a token that has a valid header + kid but
    unparseable claims raises UnauthorizedError.

    python-jose's `get_unverified_claims` is lenient, but a completely
    malformed base64 payload should trigger JWTError.
    """
    # Manually construct: header with kid, but payload is garbage base64
    import base64
    header_b64 = base64.urlsafe_b64encode(b'{"kid":"dev-kid","alg":"HS256"}').rstrip(b"=").decode()
    garbage_b64 = "this-is-not-valid-base64-for-claims!!!!"
    sig = "invalidsig"
    token = f"{header_b64}.{garbage_b64}.{sig}"

    with pytest.raises(UnauthorizedError) as exc_info:
        await auth_module._decode_token(token)
    assert "Invalid token" in str(exc_info.value)


# =============================================================================
# Dev-mode sub substitution
# =============================================================================

async def test_dev_mode_provider_sub_is_substituted() -> None:
    """
    In dev mode, `_decode_token` with `sub=dev-provider` and
    `expected_pool=providers` substitutes the sub to `settings.dev_provider_id`.
    """
    token = jwt.encode(
        {"sub": "dev-provider", "cognito:groups": ["providers"]},
        key="", algorithm="HS256",
        headers={"kid": "dev-kid"},
    )
    user = await auth_module._decode_token(token, expected_pool="providers")
    assert user.sub == settings.dev_provider_id, (
        f"expected sub={settings.dev_provider_id} for dev-provider; got {user.sub}"
    )
    assert user.pool == "providers"


async def test_dev_mode_non_provider_sub_not_substituted() -> None:
    """
    In dev mode with `expected_pool=rccm`, the sub `dev-provider` is NOT
    substituted (only substitution for providers pool).
    """
    token = jwt.encode(
        {"sub": "dev-provider", "cognito:groups": ["providers"]},
        key="", algorithm="HS256",
        headers={"kid": "dev-kid"},
    )
    user = await auth_module._decode_token(token, expected_pool="rccm")
    assert user.sub == "dev-provider", (
        f"expected sub=dev-provider (no substitution); got {user.sub}"
    )
    assert user.pool == "rccm"


async def test_dev_mode_normal_user_not_substituted() -> None:
    """
    In dev mode, a regular user sub is not substituted.
    """
    token = jwt.encode(
        {"sub": "real-user-123", "cognito:groups": ["rccm"]},
        key="", algorithm="HS256",
        headers={"kid": "dev-kid"},
    )
    user = await auth_module._decode_token(token, expected_pool="rccm")
    assert user.sub == "real-user-123"
    assert user.pool == "rccm"


# =============================================================================
# FastAPI dependency functions — no creds
# =============================================================================

async def test_current_user_no_creds_raises_unauthorized() -> None:
    """`current_user` with no credentials raises UnauthorizedError."""
    with pytest.raises(UnauthorizedError) as exc_info:
        await auth_module.current_user(creds=None)
    assert "Missing bearer token" in str(exc_info.value)


async def test_current_provider_no_creds_raises_unauthorized() -> None:
    """`current_provider` with no credentials raises UnauthorizedError."""
    with pytest.raises(UnauthorizedError) as exc_info:
        await auth_module.current_provider(creds=None)
    assert "Missing bearer token" in str(exc_info.value)


async def test_current_admin_no_creds_raises_unauthorized() -> None:
    """`current_admin` with no credentials raises UnauthorizedError."""
    with pytest.raises(UnauthorizedError) as exc_info:
        await auth_module.current_admin(creds=None)
    assert "Missing bearer token" in str(exc_info.value)


async def test_current_user_with_valid_token_returns_auth_user() -> None:
    """`current_user` with a valid dev token returns an AuthUser."""
    from fastapi.security import HTTPAuthorizationCredentials

    from tests._jwt import make_dev_jwt

    token = make_dev_jwt(sub="test-sub", pool="rccm")
    creds = HTTPAuthorizationCredentials(scheme="bearer", credentials=token)

    user = await auth_module.current_user(creds=creds)
    assert user.sub == "test-sub"
    assert user.pool == "rccm"


async def test_current_provider_with_valid_token_returns_auth_user() -> None:
    """`current_provider` with a valid dev token returns an AuthUser with pool=providers."""
    from fastapi.security import HTTPAuthorizationCredentials

    from tests._jwt import make_dev_jwt

    token = make_dev_jwt(sub="dev-provider", pool="providers")
    creds = HTTPAuthorizationCredentials(scheme="bearer", credentials=token)

    user = await auth_module.current_provider(creds=creds)
    assert user.sub == auth_module.settings.dev_provider_id  # dev-provider → substituted
    assert user.pool == "providers"


async def test_current_admin_with_valid_token_returns_auth_user() -> None:
    """`current_admin` with a valid dev token returns an AuthUser with pool=rccm."""
    from fastapi.security import HTTPAuthorizationCredentials

    from tests._jwt import make_dev_jwt

    token = make_dev_jwt(sub="admin-user", pool="rccm")
    creds = HTTPAuthorizationCredentials(scheme="bearer", credentials=token)

    user = await auth_module.current_admin(creds=creds)
    assert user.sub == "admin-user"
    assert user.pool == "rccm"


async def test_current_user_with_non_bearer_scheme_raises_unauthorized() -> None:
    """`current_user` with a non-bearer scheme raises UnauthorizedError."""
    from fastapi.security import HTTPAuthorizationCredentials

    creds = HTTPAuthorizationCredentials(scheme="basic", credentials="dGVzdDp0ZXN0")
    with pytest.raises(UnauthorizedError) as exc_info:
        await auth_module.current_user(creds=creds)
    assert "Missing bearer token" in str(exc_info.value)


# =============================================================================
# JWKS cache
# =============================================================================

async def test_jwks_cache_hit_returns_cached_value() -> None:
    """
    `_JWKSCache.get()` returns cached data when within TTL.
    """
    cache = auth_module._JWKSCache()
    fake_data = {"keys": [{"kid": "test-kid"}]}
    cache.keys_by_pool["test-pool"] = fake_data
    cache.fetched_at["test-pool"] = 9999999999.0  # far in the future

    result = await cache.get("test-pool")
    assert result == fake_data
    assert result["keys"][0]["kid"] == "test-kid"


# =============================================================================
# _cognito_client_for
# =============================================================================

def test_cognito_client_for_maps_mobbit() -> None:
    """`_cognito_client_for` returns the mobbit client id."""
    result = auth_module._cognito_client_for(settings, "mobbit")
    assert result == settings.cognito_client_mobbit


def test_cognito_client_for_maps_providers() -> None:
    """`_cognito_client_for` returns the providers client id."""
    result = auth_module._cognito_client_for(settings, "providers")
    assert result == settings.cognito_client_providers


def test_cognito_client_for_maps_rccm() -> None:
    """`_cognito_client_for` returns the rccm client id."""
    result = auth_module._cognito_client_for(settings, "rccm")
    assert result == settings.cognito_client_rccm


def test_settings_has_cognito_client_for_monkey_patch() -> None:
    """`Settings.cognito_client_for` is monkey-patched to `_cognito_client_for`."""
    from app.config import Settings

    assert hasattr(Settings, "cognito_client_for"), (
        "Settings should have a cognito_client_for method (monkey-patched)"
    )
    result = settings.cognito_client_for("rccm")
    assert result == settings.cognito_client_rccm
