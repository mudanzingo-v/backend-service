"""
Admin salers HTTP integration tests.

Five CRUD tests for `app/api/admin/salers.py`. Exercises the
create / list / get / update / delete endpoints via the in-process
ASGI client with admin auth.

Uses unique names per test (uuid4 hex prefix) to avoid pollution
collisions with prior test runs.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient

from app.schemas import SalerCreate


def _unique_name() -> str:
    return f"saler-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def saler_create_body() -> SalerCreate:
    """A unique SalerCreate body per test."""
    return SalerCreate(name=_unique_name(), email=f"{_unique_name()}@example.com")


async def test_create_saler_returns_201_with_body(
    client: AsyncClient,
    saler_create_body: SalerCreate,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`POST /api/admin/saler` returns 201 + SalerRead with all fields."""
    resp = await client.post(
        "/api/admin/saler",
        json=saler_create_body.model_dump(mode="json"),
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["name"] == saler_create_body.name
    assert body["email"] == saler_create_body.email
    assert "id" in body and body["id"]


async def test_list_salers_returns_paginated_results(
    client: AsyncClient,
    saler_create_body: SalerCreate,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/saler` returns 200 + JSON list + pagination headers."""
    # Seed a saler so the list is non-empty.
    create_resp = await client.post(
        "/api/admin/saler",
        json=saler_create_body.model_dump(mode="json"),
        headers=auth_header(dev_jwt_admin),
    )
    assert create_resp.status_code == 201

    resp = await client.get(
        "/api/admin/saler?limit=10&offset=0",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    for header in ("X-Total-Count", "X-Limit", "X-Offset", "X-Has-Next"):
        assert header in resp.headers, (
            f"missing pagination header {header!r}"
        )


async def test_get_saler_returns_200_with_body(
    client: AsyncClient,
    saler_create_body: SalerCreate,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/saler/{id}` returns 200 + matching SalerRead."""
    create_resp = await client.post(
        "/api/admin/saler",
        json=saler_create_body.model_dump(mode="json"),
        headers=auth_header(dev_jwt_admin),
    )
    saler_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/admin/saler/{saler_id}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    assert resp.json()["id"] == saler_id
    assert resp.json()["name"] == saler_create_body.name


async def test_update_saler_returns_200_with_updated_body(
    client: AsyncClient,
    saler_create_body: SalerCreate,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`PUT /api/admin/saler/{id}` updates only the provided fields."""
    create_resp = await client.post(
        "/api/admin/saler",
        json=saler_create_body.model_dump(mode="json"),
        headers=auth_header(dev_jwt_admin),
    )
    saler_id = create_resp.json()["id"]

    new_email = f"updated-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.put(
        f"/api/admin/saler/{saler_id}",
        json={"email": new_email},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == new_email
    assert body["name"] == saler_create_body.name


async def test_delete_saler_returns_200_with_message(
    client: AsyncClient,
    saler_create_body: SalerCreate,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`DELETE /api/admin/saler/{id}` returns 200 + Message confirming deletion."""
    create_resp = await client.post(
        "/api/admin/saler",
        json=saler_create_body.model_dump(mode="json"),
        headers=auth_header(dev_jwt_admin),
    )
    saler_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/admin/saler/{saler_id}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "message" in body
    assert "deleted" in body["message"].lower()
    assert saler_id in body["message"]
