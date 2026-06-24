"""
Cognito JWT validation.

The original Rust Lambdas relied on API Gateway's Cognito authorizer to
validate the JWT and inject `sub` into `request_context.authorizer.claims`.
In FastAPI we do the same validation in-process:

  1. Extract `Authorization: Bearer <jwt>` from the request.
  2. Decode the header to find the `kid` (key id).
  3. Fetch the JWKS for the corresponding user pool (cached in-memory).
  4. Verify signature, `iss`, `aud` (client_id), and `exp`.
  5. Return the claims (including `sub` = provider_id / admin_id).

In `local` or `dev` (with `AUTH_SKIP_VERIFICATION=true`) we still decode
the JWT but skip the signature check. NEVER use this in prod.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from fastapi import Depends, Header, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWTClaimsError

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
from app.core.exceptions import UnauthorizedError


# ---- JWKS cache (in-memory, refresh every 10 min) ----
@dataclass
class _JWKSCache:
    keys_by_pool: dict[str, dict[str, Any]] = field(default_factory=dict)
    fetched_at: dict[str, float] = field(default_factory=dict)
    ttl_seconds: int = 600

    async def get(self, user_pool_id: str) -> dict[str, Any]:
        now = time.time()
        if (
            user_pool_id in self.keys_by_pool
            and now - self.fetched_at.get(user_pool_id, 0) < self.ttl_seconds
        ):
            return self.keys_by_pool[user_pool_id]

        url = settings.cognito_jwks_url(user_pool_id)
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        self.keys_by_pool[user_pool_id] = data
        self.fetched_at[user_pool_id] = now
        return data


_jwks_cache = _JWKSCache()


# ---- Authenticated user ----
@dataclass
class AuthUser:
    """The decoded JWT claims plus the pool it came from."""

    sub: str
    pool: Literal["mobbit", "providers", "rccm"]
    claims: dict[str, Any]


# ---- Security scheme ----
_bearer = HTTPBearer(auto_error=False)


async def _decode_token(
    token: str,
    expected_pool: Literal["mobbit", "providers", "rccm"] | None = None,
) -> AuthUser:
    """
    Decode (and optionally verify) a Cognito JWT and return an `AuthUser`.

    `expected_pool` restricts which user pool is accepted. If `None`, any
    of the 3 pools is accepted.

    In dev mode (`AUTH_SKIP_VERIFICATION=true`), we accept any token that
    is a parseable JWT — we just decode the claims without checking the
    signature, the kid, or the JWKS. This is intended for local dev with
    the front-backoffice's dev provider; NEVER enable in prod.
    """
    # Safety: only allow skip-verification in local/dev environments
    if settings.auth_skip_verification and not settings.is_local:
        raise UnauthorizedError(
            "AUTH_SKIP_VERIFICATION is only allowed when APP_ENV is local or dev"
        )

    # Header to find kid (just for logging; we still need to parse it to
    # validate the token is a JWT at all)
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise UnauthorizedError(f"Invalid token header: {e}") from e

    kid = unverified_header.get("kid")
    if not kid:
        raise UnauthorizedError("Token missing 'kid' in header")

    # --- Dev mode fast path: accept any parseable JWT ---
    if settings.auth_skip_verification:
        try:
            claims = jwt.get_unverified_claims(token)
        except JWTError as e:
            raise UnauthorizedError(f"Invalid token claims: {e}") from e
        sub = claims.get("sub", "dev-user")
        # Dev mode special: if the token has sub="dev-provider" and
        # we're authenticating a provider, substitute the configured
        # dev_provider_id. Lets the front-provider app demo as a real
        # provider without setting up Cognito.
        if sub == "dev-provider" and expected_pool == "providers":
            sub = settings.dev_provider_id
        pool = expected_pool or "rccm"
        log.debug("Dev-mode auth: sub=%s pool=%s", sub, pool)
        return AuthUser(sub=sub, pool=pool, claims=claims)

    # --- Production: full Cognito verification ---
    # Decide which pool this token belongs to (try all if expected_pool not set).
    pools_to_try: list[tuple[Literal["mobbit", "providers", "rccm"], str]] = []
    if expected_pool == "mobbit" or expected_pool is None:
        pools_to_try.append(("mobbit", settings.cognito_user_pool_mobbit))
    if expected_pool == "providers" or expected_pool is None:
        pools_to_try.append(("providers", settings.cognito_user_pool_providers))
    if expected_pool == "rccm" or expected_pool is None:
        pools_to_try.append(("rccm", settings.cognito_user_pool_mobbit))

    last_error: Exception | None = None
    for pool_name, pool_id in pools_to_try:
        try:
            jwks = await _jwks_cache.get(pool_id)
            key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
            if not key:
                continue  # try next pool

            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=settings.cognito_client_for(pool_name),
                issuer=settings.cognito_issuer(pool_id),
                options={"verify_aud": True, "verify_iss": True, "verify_exp": True},
            )

            sub = claims.get("sub")
            if not sub:
                raise UnauthorizedError("Token missing 'sub' claim")

            return AuthUser(sub=sub, pool=pool_name, claims=claims)
        except ExpiredSignatureError as e:
            raise UnauthorizedError("Token expired") from e
        except JWTClaimsError as e:
            last_error = e
            continue
        except JWTError as e:
            last_error = e
            continue

    raise UnauthorizedError(f"Token not valid for any known pool: {last_error}")


# ---- FastAPI dependencies ----
async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """Any authenticated user (mobbit, providers, or rccm)."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthorizedError("Missing bearer token")
    return await _decode_token(creds.credentials)


async def current_provider(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """A provider (Cognito `providers` user pool)."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthorizedError("Missing bearer token")
    return await _decode_token(creds.credentials, expected_pool="providers")


async def current_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """An admin (Cognito `rccm-users` user pool)."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthorizedError("Missing bearer token")
    return await _decode_token(creds.credentials, expected_pool="rccm")


# ---- Patches to settings for cleaner code ----
def _cognito_client_for(self, pool: str) -> str:
    return {
        "mobbit": self.cognito_client_mobbit,
        "providers": self.cognito_client_providers,
        "rccm": self.cognito_client_rccm,
    }[pool]


# Monkey-patch the settings class so `settings.cognito_client_for("rccm")` works.
from app.config import Settings  # noqa: E402

Settings.cognito_client_for = _cognito_client_for  # type: ignore[attr-defined]
