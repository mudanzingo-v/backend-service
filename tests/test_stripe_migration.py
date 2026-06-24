"""
Alembic migration tests for `0004_stripe_replacement`.

Three scenarios (per `req-stripe-model-and-auction-swap-001`):

- `test_alembic_upgrade_downgrade_roundtrip` — upgrade head -> downgrade
  -1 -> upgrade head. Schema must be identical at each step.
- `test_migration_preserves_payment_id_data` — a row with
  `mp_payment_id="pi_old_xyz"` at 0003 must have
  `stripe_payment_intent_id="pi_old_xyz"` at 0004 (data preserved across
  the column rename).
- `test_migration_drops_mp_status_detail` — `mp_status_detail` does not
  exist in the schema after upgrade.

Each test creates a **dedicated throwaway database** (e.g.
`mobbit_test_mig_a1b2c3`), runs alembic against it via
`loop.run_in_executor` (alembic's command API is sync), asserts, then
drops the DB. This avoids polluting `mobbit_test` (the conftest's
`migrate` fixture would race with our subprocess alembic invocation).

Connection management: asyncpg.Connection does NOT support
`async with` directly, so each test uses `try` / `finally` for cleanup.
"""
from __future__ import annotations

import asyncio
import uuid

import asyncpg

# ---- Helpers ---------------------------------------------------------------


def _dev_admin_dsn() -> str:
    """Plain libpq DSN to the `mobbit` maintenance DB (no driver prefix).

    Use 127.0.0.1 to bypass DNS resolution — the conftest's choice of
    `localhost` works in a fresh event loop, but the executor thread
    inside a running loop can't always resolve it.
    """
    return "postgresql://mobbit:mobbit@127.0.0.1:5432/mobbit"


def _unique_db_name() -> str:
    return f"mobbit_test_mig_{uuid.uuid4().hex[:8]}"


async def _create_db(name: str) -> None:
    """Create a fresh database `name` via the `mobbit` admin DB."""
    dsn = _dev_admin_dsn()
    head = dsn.rsplit("/", 1)[0] + "/"
    admin_dsn = head + "mobbit"
    conn = await asyncpg.connect(dsn=admin_dsn)
    try:
        # Identifier is UUID-derived (safe to interpolate). Double-quoted
        # to preserve case in the identifier.
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def _drop_db(name: str) -> None:
    """Drop database `name`, terminating any lingering connections first."""
    dsn = _dev_admin_dsn()
    head = dsn.rsplit("/", 1)[0] + "/"
    admin_dsn = head + "mobbit"
    conn = await asyncpg.connect(dsn=admin_dsn)
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{name}' AND pid <> pg_backend_pid()"
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        await conn.close()


def _alembic_sync(verb: str, revision: str, db_url: str) -> None:
    """Run `alembic {verb} {revision}` against `db_url` via subprocess.

    The in-process `loop.run_in_executor(..., command.upgrade)` pattern
    used by `tests/_db.py::run_alembic_upgrade_head` fails with
    `socket.gaierror: Temporary failure in name resolution` when called
    from within an active event loop (DNS doesn't resolve in the worker
    thread). The subprocess approach sidesteps that by getting a fresh
    Python interpreter + event loop for each alembic invocation.
    """
    import os
    import pathlib
    import subprocess

    # Resolve the alembic executable relative to this file.
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    alembic_bin = repo_root / ".venv" / "bin" / "alembic"

    env = {**os.environ, "DATABASE_URL": db_url}
    result = subprocess.run(
        [str(alembic_bin), "-c", "alembic.ini", verb, revision],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo_root),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {verb} {revision} failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class _EphemeralMigrationDB:
    """Throwaway DB for migration tests; alembic ops via `await db.alembic(...)`.

    Usage:
        async with _EphemeralMigrationDB() as db:
            await db.alembic("upgrade", "0003_auction_admin_budget")
            # ... inspect schema (open / close connections explicitly) ...
            await db.alembic("upgrade", "head")
            # ... assert ...
    """

    def __init__(self) -> None:
        self.name: str = ""
        self.sqlalchemy_url: str = ""
        self.asyncpg_dsn: str = ""

    async def __aenter__(self) -> _EphemeralMigrationDB:
        self.name = _unique_db_name()
        # Use 127.0.0.1 (not localhost) to avoid DNS resolution issues
        # in the alembic subprocess and the executor thread.
        self.asyncpg_dsn = f"postgresql://mobbit:mobbit@127.0.0.1:5432/{self.name}"
        self.sqlalchemy_url = (
            f"postgresql+asyncpg://mobbit:mobbit@127.0.0.1:5432/{self.name}"
        )
        await _create_db(self.name)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        await _drop_db(self.name)

    async def alembic(self, verb: str, revision: str) -> None:
        """Run `alembic {verb} {revision}` against this DB (subprocess)."""
        # Run the subprocess in a thread so we don't block the event loop.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _alembic_sync, verb, revision, self.sqlalchemy_url
        )


# ---- Scenario 1: upgrade -> downgrade -> upgrade roundtrip -----------------


async def test_alembic_upgrade_downgrade_roundtrip() -> None:
    """
    `alembic upgrade head` -> `alembic downgrade -1` -> `alembic upgrade head`.

    Schema at 0003 before and after the roundtrip is identical. Schema
    at 0004 after the second upgrade has the `checkout_sessions` table
    and the renamed `payments.stripe_*` columns.
    """
    async with _EphemeralMigrationDB() as db:
        # ---- Bring DB to 0003 ----
        await db.alembic("upgrade", "0003_auction_admin_budget")

        # ---- Snapshot schema at 0003 ----
        conn = await asyncpg.connect(dsn=db.asyncpg_dsn)
        try:
            cols_pre = {
                r["column_name"]
                for r in await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'preferences'"
                )
            }
            tables_pre = {
                r["table_name"]
                for r in await conn.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            }
            assert "preferences" in tables_pre
            assert "checkout_sessions" not in tables_pre
            assert "mp_id" in cols_pre
        finally:
            await conn.close()

        # ---- Upgrade to 0004 (head) ----
        await db.alembic("upgrade", "head")
        conn = await asyncpg.connect(dsn=db.asyncpg_dsn)
        try:
            cols_mid = {
                r["column_name"]
                for r in await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'checkout_sessions'"
                )
            }
            tables_mid = {
                r["table_name"]
                for r in await conn.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            }
            assert "checkout_sessions" in tables_mid
            assert "preferences" not in tables_mid
            assert "stripe_session_id" in cols_mid
            payments_cols = {
                r["column_name"]
                for r in await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'payments'"
                )
            }
            assert "stripe_payment_intent_id" in payments_cols
        finally:
            await conn.close()

        # ---- Downgrade back to 0003 ----
        await db.alembic("downgrade", "-1")
        conn = await asyncpg.connect(dsn=db.asyncpg_dsn)
        try:
            cols_post = {
                r["column_name"]
                for r in await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'preferences'"
                )
            }
            tables_post = {
                r["table_name"]
                for r in await conn.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            }
            v = await conn.fetchval("SELECT version_num FROM alembic_version")
            assert v == "0003_auction_admin_budget", (
                f"expected version 0003 after downgrade; got {v}"
            )

            # The pre- and post-downgrade schemas must be identical
            # (this is the roundtrip invariant).
            assert tables_post == tables_pre, (
                f"tables differ after roundtrip: pre={tables_pre} post={tables_post}"
            )
            assert cols_post == cols_pre, (
                f"preferences columns differ after roundtrip: "
                f"pre={cols_pre} post={cols_post}"
            )
        finally:
            await conn.close()

        # ---- Re-upgrade to 0004 (head) ----
        await db.alembic("upgrade", "head")
        conn = await asyncpg.connect(dsn=db.asyncpg_dsn)
        try:
            v = await conn.fetchval("SELECT version_num FROM alembic_version")
            assert v == "0004_stripe_replacement"
            tables_final = {
                r["table_name"]
                for r in await conn.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            }
            assert "checkout_sessions" in tables_final
            assert "preferences" not in tables_final
        finally:
            await conn.close()


# ---- Scenario 2: data preservation across the column rename ----------------


async def test_migration_preserves_payment_id_data() -> None:
    """
    A `payments` row with `id="abc-123"` and `mp_payment_id="pi_old_xyz"`
    at 0003 is queryable at 0004 with `id="abc-123"` AND
    `stripe_payment_intent_id="pi_old_xyz"` (data preserved across rename).
    """
    async with _EphemeralMigrationDB() as db:
        # ---- Bring DB to 0003 ----
        await db.alembic("upgrade", "0003_auction_admin_budget")

        # ---- Seed a payments row at 0003 ----
        conn = await asyncpg.connect(dsn=db.asyncpg_dsn)
        try:
            # Need a quotation row to satisfy the FK on payments.quotation_id.
            # `created_at` is NOT NULL with a default in the model, but the
            # server default may not fire on direct INSERT via raw SQL, so we
            # supply it explicitly.
            await conn.execute(
                "INSERT INTO quotations (id, client_name, client_phone, client_email, created_at, updated_at, wizard_complete) "
                "VALUES ($1, $2, $3, $4, NOW(), NOW(), false)",
                "quot-123",
                "Test Client",
                "+525511111111",
                "test@example.com",
            )
            await conn.execute(
                "INSERT INTO payments (id, quotation_id, type, state, "
                "mp_payment_id, mp_preference_id, mp_status, mp_status_detail, "
                "currency, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())",
                "abc-123",
                "quot-123",
                "MERCADOPAGO",
                "PENDING",
                "pi_old_xyz",
                "pref_old_abc",
                "approved",
                "some detail",
                "MXN",
            )
        finally:
            await conn.close()

        # ---- Upgrade to 0004 (head) ----
        await db.alembic("upgrade", "head")

        # ---- Query the row at 0004 ----
        conn = await asyncpg.connect(dsn=db.asyncpg_dsn)
        try:
            row = await conn.fetchrow(
                "SELECT id, stripe_payment_intent_id, stripe_checkout_session_id, "
                "stripe_payment_status FROM payments WHERE id = $1",
                "abc-123",
            )
            assert row is not None, "row abc-123 missing after upgrade"
            assert row["id"] == "abc-123"
            assert row["stripe_payment_intent_id"] == "pi_old_xyz", (
                f"expected stripe_payment_intent_id='pi_old_xyz'; "
                f"got {row['stripe_payment_intent_id']!r}"
            )
            assert row["stripe_checkout_session_id"] == "pref_old_abc", (
                f"expected stripe_checkout_session_id='pref_old_abc'; "
                f"got {row['stripe_checkout_session_id']!r}"
            )
            assert row["stripe_payment_status"] == "approved"
        finally:
            await conn.close()


# ---- Scenario 3: mp_status_detail is dropped -------------------------------


async def test_migration_drops_mp_status_detail() -> None:
    """
    Column `mp_status_detail` does NOT exist in the schema after upgrade
    (verified via `information_schema.columns`).
    """
    async with _EphemeralMigrationDB() as db:
        # ---- Bring DB to 0003 ----
        await db.alembic("upgrade", "0003_auction_admin_budget")

        # ---- Sanity: at 0003 the column exists ----
        conn = await asyncpg.connect(dsn=db.asyncpg_dsn)
        try:
            pre = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'payments' AND column_name = 'mp_status_detail'"
            )
            assert pre == 1, "mp_status_detail should exist at 0003"
        finally:
            await conn.close()

        # ---- Upgrade to 0004 (head) ----
        await db.alembic("upgrade", "head")

        # ---- Post: the column is gone ----
        conn = await asyncpg.connect(dsn=db.asyncpg_dsn)
        try:
            post = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'payments' AND column_name = 'mp_status_detail'"
            )
            assert post is None, (
                "mp_status_detail still exists after upgrade (must be dropped)"
            )
        finally:
            await conn.close()