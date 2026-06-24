"""
Admin catalog HTTP integration tests.

Tests for `app/api/admin/catalog.py` covering:
  - Products CRUD (via `_make_crud_routes` factory): 4 tests
  - Services CRUD (via `_make_crud_routes` factory): 4 tests
  - Inventory Categories CRUD: 3 tests
  - Inventory Items CRUD: 3 tests
  - /inventory/items list-all: 1 test

The Products and Services tests are parameterized over the
`_make_crud_routes` factory because both entities share the same
endpoint shape (POST, GET list, GET id, PUT id, DELETE id).
"""
from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventoryCategory


def _unique() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Products + Services via _make_crud_routes factory (parameterized)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "entity_prefix,create_body_factory",
    [
        (
            "product",
            lambda u: {"name": f"prod-{u}", "description": "Test product"},
        ),
        (
            "service",
            lambda u: {"name": f"svc-{u}", "price": "100.00"},
        ),
    ],
)
async def test_crud_create_returns_201(
    client: AsyncClient,
    entity_prefix: str,
    create_body_factory,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`POST /api/admin/{prefix}` returns 201 + the created entity."""
    u = _unique()
    body = create_body_factory(u)
    resp = await client.post(
        f"/api/admin/{entity_prefix}",
        json=body,
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r} "
        f"(prefix={entity_prefix})"
    )
    assert "id" in resp.json()
    assert resp.json()["name"] == body["name"]


@pytest.mark.parametrize("entity_prefix", ["product", "service"])
async def test_crud_list_returns_200_with_pagination(
    client: AsyncClient,
    entity_prefix: str,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/{prefix}` returns 200 + JSON list + pagination headers."""
    resp = await client.get(
        f"/api/admin/{entity_prefix}?limit=10&offset=0",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    assert isinstance(resp.json(), list)
    for header in ("X-Total-Count", "X-Limit", "X-Offset", "X-Has-Next"):
        assert header in resp.headers, f"missing pagination header {header!r}"


@pytest.mark.parametrize("entity_prefix", ["product", "service"])
async def test_crud_get_by_id_returns_200(
    client: AsyncClient,
    entity_prefix: str,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/{prefix}/{id}` returns 200 + matching entity."""
    u = _unique()
    body: dict = {"name": f"{entity_prefix}-{u}"}
    if entity_prefix == "service":
        body["price"] = "50.00"
    create_resp = await client.post(
        f"/api/admin/{entity_prefix}",
        json=body,
        headers=auth_header(dev_jwt_admin),
    )
    entity_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/admin/{entity_prefix}/{entity_id}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    assert resp.json()["id"] == entity_id


@pytest.mark.parametrize("entity_prefix", ["product", "service"])
async def test_crud_delete_returns_200_with_message(
    client: AsyncClient,
    entity_prefix: str,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`DELETE /api/admin/{prefix}/{id}` returns 200 + Message."""
    u = _unique()
    body: dict = {"name": f"del-{entity_prefix}-{u}"}
    if entity_prefix == "service":
        body["price"] = "10.00"
    create_resp = await client.post(
        f"/api/admin/{entity_prefix}",
        json=body,
        headers=auth_header(dev_jwt_admin),
    )
    entity_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/admin/{entity_prefix}/{entity_id}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    body_out = resp.json()
    assert "message" in body_out
    assert "deleted" in body_out["message"].lower()


# ---------------------------------------------------------------------------
# Inventory Categories
# ---------------------------------------------------------------------------

async def test_create_inventory_category_returns_201(
    client: AsyncClient,
    db_session: AsyncSession,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`POST /api/admin/inventory/category` returns 201 + InventoryCategoryRead."""
    u = _unique()
    resp = await client.post(
        "/api/admin/inventory/category",
        json={"name": f"cat-{u}"},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["name"] == f"cat-{u}"


async def test_list_inventory_categories_returns_200(
    client: AsyncClient,
    db_session: AsyncSession,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/inventory/category` returns 200 + JSON list."""
    # Seed one category.
    cat = InventoryCategory(name=f"cat-{_unique()}")
    db_session.add(cat)
    await db_session.commit()

    resp = await client.get(
        "/api/admin/inventory/category",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_inventory_category_raises_not_found_for_synthetic(
    client: AsyncClient,
    db_session: AsyncSession,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /inventory/category/{id}` for a synthetic category 404s."""
    cat = InventoryCategory(name="synthetic-foo")
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)

    resp = await client.get(
        f"/api/admin/inventory/category/{cat.id}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 404, (
        f"synthetic category must 404; got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Inventory Items
# ---------------------------------------------------------------------------

async def test_create_inventory_item_returns_201(
    client: AsyncClient,
    db_session: AsyncSession,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`POST /api/admin/inventory/category/{cat_id}/item` returns 201."""
    cat = InventoryCategory(name=f"cat-{_unique()}")
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)

    resp = await client.post(
        f"/api/admin/inventory/category/{cat.id}/item",
        json={"name": f"item-{_unique()}"},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["category_id"] == cat.id


async def test_list_inventory_items_returns_200(
    client: AsyncClient,
    db_session: AsyncSession,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/inventory/category/{cat_id}/item` returns 200 + list."""
    cat = InventoryCategory(name=f"cat-{_unique()}")
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)

    resp = await client.get(
        f"/api/admin/inventory/category/{cat.id}/item",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_all_inventory_items_returns_200_with_pagination(
    client: AsyncClient,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/inventory/items` returns 200 + list + pagination."""
    resp = await client.get(
        "/api/admin/inventory/items?limit=10&offset=0",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    for header in ("X-Total-Count", "X-Limit", "X-Offset", "X-Has-Next"):
        assert header in resp.headers, f"missing pagination header {header!r}"
