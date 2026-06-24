"""
OpenAPI snapshot regression test.

Pins the exact OpenAPI 3.1 schema served at `/openapi.json`. Any
accidental change to a path, parameter, request/response shape, or
component definition will fail this test.

Usage:
  # Default: compare against the committed snapshot.
  pytest tests/test_openapi_snapshot.py

  # Update mode (regenerates the snapshot to match the current app):
  OPENAPI_SNAPSHOT_UPDATE=1 pytest tests/test_openapi_snapshot.py

The snapshot file lives at `tests/snapshots/openapi.json` and is
committed alongside the test. The schema is pretty-printed (indent=2,
sorted keys) for clean diffs in PR review.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "openapi.json"


def _get_openapi_schema() -> dict:
    """Generate the live OpenAPI schema from the FastAPI app."""
    from app.main import app
    return app.openapi()


@pytest.fixture(scope="module")
def live_schema() -> dict:
    return _get_openapi_schema()


def test_openapi_snapshot_is_up_to_date(live_schema: dict) -> None:
    """
    The committed snapshot must match the live schema exactly.

    On accidental changes (added/removed endpoint, schema rename,
    status code change, etc.), the test fails with a diff so the
    developer can either:
    1. Revert the unintended change, OR
    2. Acknowledge it and regenerate the snapshot (OPENAPI_SNAPSHOT_UPDATE=1).
    """
    pretty = json.dumps(live_schema, indent=2, sort_keys=True) + "\n"

    if os.environ.get("OPENAPI_SNAPSHOT_UPDATE") == "1":
        SNAPSHOT_PATH.write_text(pretty)
        pytest.skip(f"snapshot updated at {SNAPSHOT_PATH}; "
                    f"re-run without OPENAPI_SNAPSHOT_UPDATE to verify")

    if not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.write_text(pretty)
        pytest.fail(
            f"snapshot did not exist; created at {SNAPSHOT_PATH}. "
            f"Inspect the new snapshot, then commit it. "
            f"To regenerate, re-run with OPENAPI_SNAPSHOT_UPDATE=1."
        )

    committed = SNAPSHOT_PATH.read_text()
    if committed != pretty:
        # Write the actual diff to a sibling file for easier inspection.
        diff_path = SNAPSHOT_PATH.with_suffix(".actual.json")
        diff_path.write_text(pretty)
        pytest.fail(
            f"OpenAPI snapshot mismatch. Live schema written to {diff_path}. "
            f"Diff against {SNAPSHOT_PATH}. "
            f"If the change is intentional, re-run with "
            f"OPENAPI_SNAPSHOT_UPDATE=1 to regenerate the snapshot."
        )
