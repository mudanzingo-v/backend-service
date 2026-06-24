"""Shared pytest fixtures for the mobbit-backend-service smoke suite.

CRITICAL — env-var ordering
---------------------------
The env-var override block at the top of this file MUST run **before**
any `from app.*` import. `pydantic-settings` caches the `Settings()`
instance on first instantiation (see `app/config.py::get_settings`,
decorated with `@lru_cache`), so a late override is a silent no-op that
would point the tests at the dev DB instead of `mobbit_test`.

Conventions honored (see `openspec/config.yaml → conventions`)
--------------------------------------------------------------
- `dev-auth` — `AUTH_SKIP_VERIFICATION=true` only in dev. We assert
  `settings.is_local` and `settings.auth_skip_verification` at session
  start; running this suite outside `local` is a hard error (per
  `req-auth-safety-001` and design R5).
- `db-credentials` — dev creds `mobbit/mobbit/mobbit` are reused for
  the test DB, which lives on the same dev Postgres container.
- `phase-tagging` — this file is part of the Phase 3 (Tests) smoke
  suite; no production code is touched.

Fixture contract (per spec.md §"Shared fixtures")
------------------------------------------------
| Fixture             | Scope    | Yields                                          |
|---------------------|----------|-------------------------------------------------|
| `engine`            | session  | AsyncEngine pointed at `mobbit_test`            |
| `migrate`           | session  | (autouse) ensures mobbit_test exists + migrates |
| `db_session`        | function | AsyncSession wrapped in BEGIN…ROLLBACK          |
| `app`               | session  | FastAPI app singleton                           |
| `client`            | function | httpx.AsyncClient over ASGITransport(app)       |
| `dev_jwt_admin`     | session  | str (HS256, sub=dev-user, pool=rccm)            |
| `dev_jwt_mobbit`    | session  | str (HS256, sub=dev-user, pool=mobbit)          |
| `dev_jwt_provider`  | session  | str (HS256, sub=dev-provider, pool=providers)   |
| `auth_header`       | function | factory: token -> {"Authorization": "Bearer …"}|
"""
# ruff: noqa: E402 — env-var block + lazy imports below MUST precede
# `from app.*` to control `pydantic-settings` instantiation order.

import os

# ---- 1. Env-var overrides (BEFORE any `from app.*`) ----
os.environ["APP_ENV"] = "local"
os.environ["AUTH_SKIP_VERIFICATION"] = "true"
os.environ["CORS_ALLOW_ORIGINS"] = (
    "http://localhost:3050,http://localhost:3051,http://localhost:3052"
)

# ---- 2. Build DATABASE_URL via the _db helper ----
# Import the helpers via the `tests.` package so mypy follows the type
# info on `make_dev_jwt` (a bare `from _jwt import …` import in a
# conftest loses the return-type annotation under `--strict`).
from tests._db import ensure_test_db_exists, make_test_database_url, run_alembic_upgrade_head  # noqa: E402, I001
from tests._jwt import _ADMIN_CLAIMS, _MOBBIT_CLAIMS, _PROVIDER_CLAIMS, make_dev_jwt  # noqa: E402, I001

os.environ["DATABASE_URL"] = make_test_database_url(
    "postgresql+asyncpg://mobbit:mobbit@localhost:5432/mobbit"
)

# ---- 3. Now safe to import app.config (its Settings is built here) ----
from app.config import settings  # noqa: E402, I001
from app.main import app as _fastapi_app  # noqa: E402, I001
from fastapi import FastAPI  # noqa: E402, I001

import pytest  # noqa: E402, I001
import pytest_asyncio  # noqa: E402, I001
from collections.abc import AsyncGenerator, Callable  # noqa: E402, I001
from httpx import ASGITransport, AsyncClient  # noqa: E402, I001
from sqlalchemy.ext.asyncio import (  # noqa: E402, I001
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# ---- 4. Safety guards (per req-auth-safety-001) ----
assert settings.is_local, (
    f"smoke suite requires APP_ENV=local/dev; got APP_ENV={settings.app_env!r}. "
    "Refusing to run tests outside the local dev environment."
)
assert settings.auth_skip_verification, (
    "smoke suite requires AUTH_SKIP_VERIFICATION=true; "
    f"got AUTH_SKIP_VERIFICATION={settings.auth_skip_verification!r}."
)


# ---- 5. Session-scoped fixtures: engine + migrate ----


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Async SQLAlchemy engine pointed at `mobbit_test`."""
    eng = create_async_engine(
        settings.database_url,
        pool_size=2,
        max_overflow=4,
        echo=False,
        pool_pre_ping=True,
    )
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def migrate() -> None:
    """Ensure `mobbit_test` exists and is at Alembic head.

    `autouse=True` so every test session — including the health-only
    smoke tests — runs against a migrated DB. This avoids false
    negatives from a fresh dev machine where `mobbit_test` doesn't yet
    exist. Idempotent: `ensure_test_db_exists` checks `pg_database`,
    and `alembic upgrade head` is a no-op when already at head.
    """
    await ensure_test_db_exists(settings.database_url)
    await run_alembic_upgrade_head(settings.database_url)


# ---- 6. Function-scoped fixture: db_session (savepoint-rollback) ----


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Async session wrapped in a savepoint-rollback transaction.

    Each test gets its own connection + outer `BEGIN`. The session is
    yielded, and the teardown rolls back so no test writes leak into
    `mobbit_test` or across tests. This is faster and simpler than
    per-test TRUNCATE (no DDL, no FK-order dance).

    Limitation: any code under test that opens its **own** session
    outside this fixture (e.g., a background task) won't see the
    uncommitted writes. Acceptable for the smoke suite; a
    `db_session_no_rollback` fixture can be added in a follow-up.
    """
    maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with maker() as session:
        try:
            yield session
        finally:
            await session.rollback()


# ---- 7. Session-scoped JWT fixtures (3 prebuilt tokens) ----


@pytest.fixture(scope="session")
def dev_jwt_admin() -> str:
    """HS256 dev-jwt with `sub=dev-user`, `pool=rccm` (admin backoffice)."""
    return make_dev_jwt(sub=_ADMIN_CLAIMS["sub"], pool=_ADMIN_CLAIMS["pool"])


@pytest.fixture(scope="session")
def dev_jwt_mobbit() -> str:
    """HS256 dev-jwt with `sub=dev-user`, `pool=mobbit` (B2C pool)."""
    return make_dev_jwt(sub=_MOBBIT_CLAIMS["sub"], pool=_MOBBIT_CLAIMS["pool"])


@pytest.fixture(scope="session")
def dev_jwt_provider() -> str:
    """HS256 dev-jwt with `sub=dev-provider`, `pool=providers`.

    The auth module substitutes `sub="dev-provider"` to
    `settings.dev_provider_id` for the provider pool (see
    `app/core/auth.py:75-77`). The `sub` here MUST be exactly
    `"dev-provider"` for the substitution to fire.
    """
    return make_dev_jwt(sub=_PROVIDER_CLAIMS["sub"], pool=_PROVIDER_CLAIMS["pool"])


# ---- 8. Session-scoped fixture: app ----


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """The FastAPI app singleton, already built with test settings.

    Imported here (not at module top) so the env-var override block
    runs first. `ASGITransport` does NOT run the FastAPI `lifespan`
    context manager — for this app, lifespan only sets up logging,
    which tests don't depend on.
    """
    return _fastapi_app


# ---- 9. Function-scoped fixture: client (in-process ASGI) ----


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """`httpx.AsyncClient` over `ASGITransport(app)` — no port binding.

    Faster than hitting `localhost:8765`, no TCP roundtrip, and
    deterministic. Each test gets a fresh client; teardown closes it.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---- 10. Function-scoped fixture: auth_header (factory) ----


@pytest.fixture
def auth_header() -> Callable[[str], dict[str, str]]:
    """Factory: build an `Authorization: Bearer <token>` header dict."""
    def _factory(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}
    return _factory