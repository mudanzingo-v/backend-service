"""Dev-JWT minting helpers for the mobbit-backend-service smoke suite.

This module is pure helpers (no fixtures, no tests). It exposes one
callable plus three prebuilt claim dicts:

- `make_dev_jwt(sub, pool, *, email=None, name=None, exp_seconds=3600)`
  — mints an HS256-signed JWT with a `kid="dev-kid"` header. The
  backend's `AUTH_SKIP_VERIFICATION` branch (`app/core/auth.py:74-77`)
  decodes the **unverified** claims — it never inspects the signature —
  so a parseable HS256 token with a `kid` header is accepted in dev
  mode.

  `python-jose` refuses to encode with `alg=none`; HS256 with `key=""`
  is the documented escape hatch (matches what `front-backoffice/lib/auth.ts
  → makeFakeJwt` produces, modulo the algorithm field).

- `_ADMIN_CLAIMS`, `_MOBBIT_CLAIMS`, `_PROVIDER_CLAIMS` — module-level
  dict literals for the three prebuilt tokens. Consumed by
  `tests/conftest.py` fixtures (`dev_jwt_admin`, `dev_jwt_mobbit`,
  `dev_jwt_provider`).

No new deps are added — `python-jose[cryptography]` is already pinned
in `pyproject.toml [project.dependencies]`.
"""
from __future__ import annotations

import time

from jose import jwt


def make_dev_jwt(
    sub: str,
    pool: str,
    *,
    email: str | None = None,
    name: str | None = None,
    exp_seconds: int = 3600,
) -> str:
    """Mint a dev-mode JWT that `app/core/auth.py` accepts under
    `AUTH_SKIP_VERIFICATION=true && APP_ENV=local`.

    Claims mirror what the frontends produce in dev mode
    (`front-backoffice/lib/auth.ts → makeFakeJwt`,
    `front-provider/lib/auth.ts → makeFakeJwt`):

        {
            "sub": <sub>,
            "email": <email>,
            "name": <name>,
            "cognito:username": <sub>,
            "cognito:groups": [<pool>],
            "iat": <now>,
            "exp": <now + exp_seconds>,
            "auth_time": <now>,
            "iss": "dev",
            "aud": "dev",
            "token_use": "id",
        }

    Args:
        sub: the `sub` claim. `app/core/auth.py` substitutes
            `sub="dev-provider"` to `settings.dev_provider_id` when
            authenticating a provider in dev mode.
        pool: the Cognito user pool (one of `rccm`, `mobbit`,
            `providers`); goes into `cognito:groups[0]`.
        email: defaults to `f"{sub}@mobbit.local"`.
        name: defaults to `sub.replace("-", " ").title()`.
        exp_seconds: token lifetime. Defaults to 1 hour.

    Returns:
        A JWT string with header `{"kid": "dev-kid", "alg": "HS256"}`.
    """
    if email is None:
        email = f"{sub}@mobbit.local"
    if name is None:
        name = sub.replace("-", " ").title()
    now = int(time.time())
    claims = {
        "sub": sub,
        "email": email,
        "name": name,
        "cognito:username": sub,
        "cognito:groups": [pool],
        "iat": now,
        "exp": now + exp_seconds,
        "auth_time": now,
        "iss": "dev",
        "aud": "dev",
        "token_use": "id",
    }
    # HS256 with key="" — backend's AUTH_SKIP_VERIFICATION branch never
    # verifies the signature, only the header `kid` and the claims. Any
    # parseable token with a `kid` is accepted.
    return jwt.encode(claims, key="", algorithm="HS256", headers={"kid": "dev-kid"})


# Prebuilt claims consumed by `tests/conftest.py` fixtures. The shape
# mirrors what each token needs to authenticate against the
# corresponding dependency in `app/core/auth.py`:
#
#   - `_ADMIN_CLAIMS` (pool="rccm"): used by `current_admin` dep
#     (`app/core/auth.py:118-122`), which expects `expected_pool="rccm"`.
#   - `_MOBBIT_CLAIMS` (pool="mobbit"): reserved for future B2C
#     auth-gated endpoints; the dev-jwt shape is forward-compatible.
#   - `_PROVIDER_CLAIMS` (pool="providers", sub="dev-provider"): used by
#     `current_provider` dep (`app/core/auth.py:113-117`), which expects
#     `expected_pool="providers"`. The auth module substitutes the `sub`
#     to `settings.dev_provider_id` (line 75-77) — so the `sub` here
#     must be exactly `"dev-provider"` for the substitution to fire.

_ADMIN_CLAIMS = {"sub": "dev-user", "pool": "rccm"}
_MOBBIT_CLAIMS = {"sub": "dev-user", "pool": "mobbit"}
_PROVIDER_CLAIMS = {"sub": "dev-provider", "pool": "providers"}


__all__ = [
    "make_dev_jwt",
    "_ADMIN_CLAIMS",
    "_MOBBIT_CLAIMS",
    "_PROVIDER_CLAIMS",
]