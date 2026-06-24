"""Test database lifecycle helpers for the mobbit-backend-service smoke suite.

This module is pure helpers (no fixtures, no tests). It exposes three
callables, all importable from any test module under `tests/`:

- `ensure_test_db_exists(database_url)` — creates `mobbit_test` on the
  dev Postgres container if missing. Connects via asyncpg to one of
  the maintenance DBs (`mobbit` first, then `postgres`, then
  `template1`) and issues `CREATE DATABASE "mobbit_test"`. Idempotent.

- `run_alembic_upgrade_head(database_url)` — runs
  `alembic.command.upgrade("head")` against the given URL. Wraps the
  sync alembic call in `loop.run_in_executor(...)` so the asyncio
  event loop is not blocked. Idempotent — alembic's version table
  skips already-applied migrations.

- `make_test_database_url(dev_database_url)` — pure string-replace
  utility. Swaps the path component (dbname) from `mobbit` to
  `mobbit_test`. Used by `tests/conftest.py` at top-of-file to build
  the `DATABASE_URL` env var before `app.config.settings` is
  imported (the `pydantic-settings` `Settings()` instance caches on
  first instantiation, so env-var ordering is critical).

No new deps are added — asyncpg, alembic, sqlalchemy are already
pinned in `pyproject.toml [project.dependencies]` and `[project.optional-dependencies].dev`.
"""
from __future__ import annotations

import asyncio

import asyncpg


def make_test_database_url(dev_database_url: str) -> str:
    """Swap the path component (dbname) to `mobbit_test`.

    Pure string operation; idempotent. Works for both
    `postgresql+asyncpg://...` (SQLAlchemy) and `postgresql://...`
    (asyncpg-native) URL forms.

    Examples:
        >>> make_test_database_url("postgresql+asyncpg://mobbit:mobbit@localhost:5432/mobbit")
        'postgresql+asyncpg://mobbit:mobbit@localhost:5432/mobbit_test'
        >>> make_test_database_url("postgresql://x:y@h:5432/mobbit_test")
        'postgresql://x:y@h:5432/mobbit_test'
    """
    idx = dev_database_url.rfind("/")
    return dev_database_url[: idx + 1] + "mobbit_test"


async def ensure_test_db_exists(database_url: str) -> None:
    """Create the `mobbit_test` database if missing. Idempotent.

    `database_url` is expected to point at `mobbit_test` (or at least
    have the same host/port/credentials as the test target). We swap
    the path component to one of the standard maintenance DBs and
    connect to issue `CREATE DATABASE` if `mobbit_test` is not in
    `pg_database`.

    asyncpg's `Connection.execute()` runs in autocommit mode by default,
    so `CREATE DATABASE` works directly (it cannot run inside a
    transaction block).
    """
    # Strip the SQLAlchemy driver prefix; asyncpg wants plain libpq URLs.
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    # Path component (everything after the last '/') is the dbname.
    idx = dsn.rfind("/")
    head = dsn[: idx + 1]  # includes trailing '/'

    last_err: BaseException | None = None
    for admin_db in ("mobbit", "postgres", "template1"):
        admin_dsn = head + admin_db
        try:
            conn = await asyncpg.connect(dsn=admin_dsn)
        except Exception as exc:  # noqa: BLE001 — fallback chain
            last_err = exc
            continue
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = 'mobbit_test'"
            )
            if not exists:
                # CREATE DATABASE cannot run in a transaction block;
                # asyncpg's autocommit default makes this safe.
                await conn.execute('CREATE DATABASE "mobbit_test"')
            return
        finally:
            await conn.close()

    raise RuntimeError(
        "could not connect to any maintenance DB to ensure mobbit_test "
        f"exists; tried mobbit/postgres/template1; last error: {last_err!r}"
    )


async def run_alembic_upgrade_head(database_url: str) -> None:
    """Run `alembic upgrade head` against `database_url`.

    Alembic's `command.upgrade` is synchronous and uses blocking I/O.
    Calling it directly in an async fixture would block the event loop
    for the duration of the migration (typically ≤ 2 s). We offload it
    to the default executor via `loop.run_in_executor(...)` so other
    fixtures can proceed in parallel.

    Idempotent — alembic's own `alembic_version` table skips already-
    applied migrations on re-runs.
    """
    # Imported lazily so module import does not require alembic at
    # collection time (e.g., `pytest --collect-only`).
    from alembic.config import Config

    from alembic import command

    def _sync_upgrade() -> None:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(cfg, "head")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _sync_upgrade)


__all__ = [
    "ensure_test_db_exists",
    "run_alembic_upgrade_head",
    "make_test_database_url",
]
