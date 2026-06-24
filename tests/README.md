# Backend smoke suite

Smoke tests for the **FastAPI backend** at `mobbit-backend-service/`. The
suite uses an **in-process ASGI client** (`httpx.AsyncClient +
ASGITransport`) against the `app` singleton — no port binding to
`:8765`, no TCP roundtrip, deterministic lifespan.

## What this is

A thin **smoke suite** for the FastAPI backend. It exercises:

- The `/health` and `/` pre-include_router endpoints return the
  documented shape.
- The shared fixtures (`app`, `client`, `db_session`, `dev_jwt_*`,
  `auth_header`) resolve cleanly — acts as a conftest-refactor safety net.
- (Follow-up `sdd-apply` runs will add OpenAPI-shape assertions,
  pagination-header integration, and dev-mode auth-path tests.)

**No production code is touched by this change.** The only edits to the
production tree are 5 lines in `pyproject.toml` (`[tool.pytest.ini_options]`)
adding `addopts` (coverage report, strict markers) and the `unit` /
`integration` marker registrations.

## Test files

The suite is built incrementally across two OpenSpec changes:

### Smoke suite (`backend-pytest-smoke-suite`, archived)

| File | Purpose |
|---|---|
| `test_health.py` | `/health` and `/` pre-include_router endpoints |
| `test_openapi.py` | `/openapi.json`, `/docs`, `/redoc`; router prefix presence |
| `test_pagination.py` | `set_pagination_headers` helper + admin pagination integration |
| `test_auth_dev_mode.py` | dev-jwt happy paths + cross-role + `AUTH_SKIP_VERIFICATION` safety guard |

### Coverage extension (`backend-pytest-coverage-80`, current)

Targets business-logic modules identified as the highest-leverage coverage gaps:

| File | Module under test | Tests | What it pins |
|---|---|---:|---|
| `test_pricing.py` | `app/services/pricing.py` | 5 | Formula contract (no-COD + COD + §5.2 bug-fix invariant + zero edge case) |
| `test_quotation_service.py` | `app/services/quotation.py` | 15 | 9 service functions + 2 state transitions (publish + cancel) with happy paths + error paths + idempotency + synthetic-record filter |
| `test_admin_quotations.py` | `app/api/admin/quotations.py` | 8 | 8 HTTP endpoints (list with pagination, CRUD, publish, cancel, assign-provider) |
| `test_admin_stats.py` | `app/api/admin/stats.py` | 2 | Aggregate counts: happy path + empty-DB edge case |

### Shared modules (helper code, not tests)

| File | Purpose |
|---|---|
| `conftest.py` | Fixtures: `app`, `client`, `db_session`, `engine`, `migrate`, `dev_jwt_admin`, `dev_jwt_mobbit`, `dev_jwt_provider`, `auth_header` |
| `_db.py` | Test DB lifecycle: `ensure_test_db_exists`, `run_alembic_upgrade_head`, `make_test_database_url` |
| `_jwt.py` | Dev-JWT minting helper (`make_dev_jwt`) + claim templates per pool |

### Coverage target

The combined suite targets **≥ 80 % global coverage** (per `ROADMAP.md`
Phase 3.1). Current state: see `pytest --cov=app --cov-report=term-missing`.

The change that flips `strict_tdd: true` and adds `--cov-fail-under=NN`
is `strict-tdd-flip-backend` (proposed). This README will be updated
when that change lands.

## Prerequisites

- **Postgres at `localhost:5432`** with dev creds `mobbit/mobbit`.
  Use `./bin/start.sh` from the workspace root to bring up the dev
  Postgres + API containers. If the dev container is not running,
  the `migrate` autouse fixture fails fast with a clear `asyncpg`
  connection error.
- The `mobbit_test` database is **auto-created** on first run by
  `tests/_db.py::ensure_test_db_exists` (connects to the `mobbit`
  maintenance DB and issues `CREATE DATABASE mobbit_test` if missing).
- Python ≥ 3.11 with `pip install -e ".[dev]"` (or
  `uv pip install -e ".[dev]"`) from inside `mobbit-backend-service/`.

## How to run

From `mobbit-backend-service/`:

```sh
# All tests in this directory
pytest

# Verbose with full tracebacks
pytest -vv --tb=long

# A specific test file
pytest tests/test_health.py

# Only integration-marked tests (the smoke tests are all integration by default)
pytest -m integration

# Only unit-marked tests (none in PR1; reserved for future pure-Python helpers)
pytest -m unit
```

From inside the dev container:

```sh
docker compose exec api pytest
```

## How to debug a failure

- `pytest -vv --tb=long` — full tracebacks, no capture.
- `pytest -k <substring>` — run only tests whose name contains the
  substring (e.g. `pytest -k health`).
- The `mobbit_test` DB is reachable from your dev host (port `5432`)
  if you have `psql` installed locally — useful to inspect the rolled-
  back state between tests:

  ```sh
  psql -U mobbit -d mobbit_test -h localhost
  ```

  Note: `psql` is **not** in the backend runtime image; it must be on
  your dev host. The smoke suite itself never shells out to `psql`.
- The `engine` fixture is **session-scoped**. A single `pytest` run
  issues one `alembic upgrade head` per fresh `mobbit_test`; subsequent
  runs are no-ops (alembic's version table tracks state).

## Markers

| Marker         | Meaning                                                       | Default |
|----------------|---------------------------------------------------------------|---------|
| `unit`         | Pure unit tests (no DB, no HTTP)                              | deselected by `-m unit` |
| `integration`  | Tests that hit the FastAPI app or the test DB                 | included by default      |

`--strict-markers` is on (see `pyproject.toml` addopts), so an unknown
marker is a hard error at collection time.

## What is **NOT** covered by this change

These items are deliberately deferred to follow-up changes:

- **Coverage threshold** (`--cov-fail-under=NN`) → `strict-tdd-flip-backend`
  (proposed). The `--cov=app --cov-report=term-missing` addopts
  generate the report; gating happens in the next change.
- **OpenAPI snapshot file** (`tests/snapshots/openapi.json`) → future
  contract-tests change.
- **MP webhook smoke test** (signature validation, payment status
  lookup) → Phase 1.1 `mp-webhook-receiver` change. The current handler
  is a documented stub (`app/api/webhooks/mercadopago.py`) that returns
  200 + `{}`; asserting it would be a tautology.
- **Frontend test runners** (`vitest` + `@testing-library/react` per
  `front-*/`) → `frontend-test-runners-bootstrap` change.
- **GitHub Actions workflow** (`.github/workflows/backend.yml`) →
  `phase-4-2-cicd-github-actions` change.
- **`bin/test.sh` wrapper** → deferred to the CI change.

## Dev-mode requirements

The conftest env-var block **asserts** at session start that:

- `APP_ENV=local` (or `dev`),
- `AUTH_SKIP_VERIFICATION=true`.

If either guard fails, pytest fails fast with a `RuntimeError` naming
the offending variable. This prevents accidentally running the suite
against a `staging` or `prod` environment (per the `dev-auth`
convention in `openspec/config.yaml`).
