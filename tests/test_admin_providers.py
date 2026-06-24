"""
Admin providers HTTP integration tests.

Five tests for providers + three tests for trucks (8 endpoints total)
in `app/api/admin/providers.py`. Exercises CRUD + the
synthetic-record filter on `Provider.name IS NULL`.

Uses unique IDs per test (uuid4 hex) to avoid pollution collisions.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Provider


def _unique() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Provider endpoints
# ---------------------------------------------------------------------------

async def test_create_provider_returns_201_with_body(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`POST /api/admin/provider` returns 201 + ProviderRead with all fields."""
    pid = f"prov-{_unique()}"
    resp = await client.post(
        "/api/admin/provider",
        json={
            "id": pid,
            "name": f"Test Provider {_unique()}",
            "email": f"prov-{_unique()}@example.com",
            "phone": "+525588888888",
            "rfc": "TEST010101ABC",
            "active": True,
        },
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["id"] == pid
    assert "name" in body


async def test_list_providers_returns_paginated_results(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/provider` returns 200 + list + pagination headers."""
    resp = await client.get(
        "/api/admin/provider?limit=10&offset=0",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    for header in ("X-Total-Count", "X-Limit", "X-Offset", "X-Has-Next"):
        assert header in resp.headers, f"missing pagination header {header!r}"


async def test_get_provider_returns_200_with_body(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/provider/{id}` returns 200 + matching ProviderRead."""
    pid = f"prov-{_unique()}"
    await client.post(
        "/api/admin/provider",
        json={"id": pid, "name": f"Test Provider {_unique()}", "active": True},
        headers=auth_header(dev_jwt_admin),
    )

    resp = await client.get(
        f"/api/admin/provider/{pid}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["id"] == pid


async def test_update_provider_returns_200_with_updated_body(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`PUT /api/admin/provider/{id}` updates only the provided fields."""
    pid = f"prov-{_unique()}"
    await client.post(
        "/api/admin/provider",
        json={"id": pid, "name": "Original Name", "active": True},
        headers=auth_header(dev_jwt_admin),
    )

    new_phone = "+525599999999"
    resp = await client.put(
        f"/api/admin/provider/{pid}",
        json={"phone": new_phone},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["phone"] == new_phone
    assert body["name"] == "Original Name"


async def test_get_provider_raises_not_found_for_synthetic(
    client: AsyncClient,
    db_session: AsyncSession,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `GET /api/admin/provider/{id}` for a synthetic provider (name IS NULL)
    raises `NotFoundError` (returns 404). Pins the migration-glue invariant.
    """
    pid = f"synthetic-{_unique()}"
    db_session.add(Provider(id=pid, name=None, active=True))
    await db_session.commit()

    resp = await client.get(
        f"/api/admin/provider/{pid}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 404, (
        f"synthetic provider must 404; got {resp.status_code} body={resp.text!r}"
    )


# ---------------------------------------------------------------------------
# Truck endpoints
# ---------------------------------------------------------------------------

async def test_create_truck_returns_201_with_body(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`POST /api/admin/provider/{pid}/truck` returns 201 + TruckRead."""
    pid = f"prov-{_unique()}"
    # Pre-create the provider.
    await client.post(
        "/api/admin/provider",
        json={"id": pid, "name": f"Truck Provider {_unique()}", "active": True},
        headers=auth_header(dev_jwt_admin),
    )

    resp = await client.post(
        f"/api/admin/provider/{pid}/truck",
        json={
            "plates": f"ABC-{_unique()[:3].upper()}",
            "brand": "Kenworth",
            "model": "T680",
            "year": 2023,
            "capacity_kg": 30000,
            "capacity_m3": 80.0,
            "active": True,
        },
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["provider_id"] == pid
    assert body["brand"] == "Kenworth"


async def test_list_trucks_returns_paginated_results(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/provider/{pid}/truck` returns 200 + list + pagination."""
    pid = f"prov-{_unique()}"
    await client.post(
        "/api/admin/provider",
        json={"id": pid, "name": f"List Trucks Provider {_unique()}", "active": True},
        headers=auth_header(dev_jwt_admin),
    )

    resp = await client.get(
        f"/api/admin/provider/{pid}/truck?limit=10&offset=0",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    for header in ("X-Total-Count", "X-Limit", "X-Offset", "X-Has-Next"):
        assert header in resp.headers, f"missing pagination header {header!r}"


async def test_get_truck_returns_200_with_body(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/provider/{pid}/truck/{tid}` returns 200 + TruckRead."""
    pid = f"prov-{_unique()}"
    await client.post(
        "/api/admin/provider",
        json={"id": pid, "name": f"Get Truck Provider {_unique()}", "active": True},
        headers=auth_header(dev_jwt_admin),
    )
    create_resp = await client.post(
        f"/api/admin/provider/{pid}/truck",
        json={"plates": "XYZ-001", "brand": "Volvo", "active": True},
        headers=auth_header(dev_jwt_admin),
    )
    truck_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/admin/provider/{pid}/truck/{truck_id}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    assert resp.json()["id"] == truck_id


async def test_update_provider_returns_404_for_unknown_id(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    resp = await client.put(
        f"/api/admin/provider/nonexistent-{uuid.uuid4().hex}",
        json={"phone": "+525500000000"},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 404


async def test_get_truck_returns_404_for_unknown_id(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    pid = f"prov-{uuid.uuid4().hex[:12]}"
    await client.post(
        "/api/admin/provider",
        json={"id": pid, "name": "Truck Provider", "active": True},
        headers=auth_header(dev_jwt_admin),
    )
    resp = await client.get(
        f"/api/admin/provider/{pid}/truck/nonexistent-{uuid.uuid4().hex}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 404


async def test_update_truck_returns_404_for_unknown_id(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    pid = f"prov-{uuid.uuid4().hex[:12]}"
    await client.post(
        "/api/admin/provider",
        json={"id": pid, "name": "Truck Provider", "active": True},
        headers=auth_header(dev_jwt_admin),
    )
    resp = await client.put(
        f"/api/admin/provider/{pid}/truck/nonexistent-{uuid.uuid4().hex}",
        json={"brand": "Volvo"},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 404


async def test_create_truck_returns_404_for_unknown_provider(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    resp = await client.post(
        f"/api/admin/provider/nonexistent-{uuid.uuid4().hex}/truck",
        json={"plates": "X", "brand": "X", "active": True},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 404
