"""
Admin stats HTTP integration tests — `req-admin-stats-coverage-001`.

Two integration tests that exercise `app/api/admin/stats.py`:
  - happy path: returns aggregate counts for all entities
  - edge case: empty database → all counts equal 0

Auth: requires `current_admin`; uses smoke suite's `dev_jwt_admin`
via `auth_header`.

Isolation: the happy-path test asserts `count >= 1` per field rather
than `count == 1`, because pollution from prior runs (other tests'
quotations / products / etc.) can persist in `mobbit_test`. The
empty-database edge case test TRUNCATEs all 10 tables for a clean
baseline; this depends on `db_session.execute()` access which is
available via the smoke suite's `db_session` fixture.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Auction,
    InventoryCategory,
    InventoryItem,
    Payment,
    Product,
    Provider,
    Quotation,
    Saler,
    Service,
    Truck,
)


def _unique() -> str:
    """Unique tag for seeded rows so they don't collide with prior-run pollution."""
    return uuid.uuid4().hex[:12]


@pytest.fixture
async def seeded_db(db_session: AsyncSession) -> None:
    """
    Seed one row in each of the 10 tables counted by `/api/admin/stats`.

    Uses unique names/IDs (uuid4 hex prefix) so collisions with prior
    runs are impossible. The fixture is async because it awaits
    `db_session.commit()`.
    """
    u = _unique()

    # The 10 tables that the stats endpoint counts.
    # The Quotation must flush before the Payment (which FKs to it).
    q = Quotation(
        client_name=u,
        client_phone="+525511111111",
        client_email=f"{u}@example.com",
        origin_postal_code="01000",
        destination_postal_code="03100",
    )
    db_session.add(q)
    await db_session.flush()
    q_id = q.id

    db_session.add(Product(name=f"prod-{u}"))
    db_session.add(Service(name=f"svc-{u}"))
    cat = InventoryCategory(name=f"cat-{u}")
    db_session.add(cat)
    await db_session.flush()
    db_session.add(InventoryItem(name=f"inv-{u}", category_id=cat.id))
    db_session.add(Provider(id=f"prov-{u}", name=f"Test Provider {u}", active=True))
    db_session.add(Saler(name=f"saler-{u}"))
    db_session.add(Payment(
        quotation_id=q_id,
        type="INITIAL",
        state="PENDING",
        currency="MXN",
    ))
    db_session.add(Truck(provider_id=f"prov-{u}", plates=f"plat-{u}"))
    db_session.add(Auction(
        quotation_id=q_id,
        provider_id=f"prov-{u}",
        price_load=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        mobbit_fee=Decimal("5.00"),
        iva=Decimal("16.80"),
        transaction_fee=Decimal("6.09"),
        total=Decimal("127.89"),
        state="PENDING",
    ))
    await db_session.commit()


async def test_stats_returns_aggregate_counts_for_all_entities(
    client: AsyncClient,
    db_session: AsyncSession,
    seeded_db: None,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `GET /api/admin/stats` returns 200 + a `Stats` JSON with all 10
    fields ≥ 1 (after seeding at least one row in each table).

    Note: count assertions use `>= 1` rather than `== 1` to be robust
    against pollution from prior test runs (the `seeded_db` fixture
    guarantees the values are AT LEAST 1, not exactly 1).
    """
    resp = await client.get(
        "/api/admin/stats",
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    for field in (
        "quotations",
        "auctions",
        "products",
        "services",
        "inventory_items",
        "inventory_categories",
        "providers",
        "salers",
        "payments",
        "trucks",
    ):
        assert field in body, f"missing field {field!r} in stats response"
        assert body[field] >= 1, (
            f"field {field!r} should be ≥ 1 after seeding; got {body[field]}"
        )


async def test_stats_returns_zero_counts_on_empty_database(
    client: AsyncClient,
    db_session: AsyncSession,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `GET /api/admin/stats` on a fully-empty DB returns 200 + `Stats`
    JSON with all 10 fields equal to 0.

    Implementation note: the SQL filters out synthetic records in the
    quotation and category counts, so any pre-existing pollution that
    matches the synthetic markers is also filtered. The test truncates
    all 10 tables explicitly to ensure a clean baseline.
    """
    for table in (
        "quotations", "auctions", "products", "services",
        "inventory_items", "inventory_categories", "providers",
        "salers", "payments", "trucks",
    ):
        await db_session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
    await db_session.commit()

    resp = await client.get(
        "/api/admin/stats",
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    for field in (
        "quotations",
        "auctions",
        "products",
        "services",
        "inventory_items",
        "inventory_categories",
        "providers",
        "salers",
        "payments",
        "trucks",
    ):
        assert body[field] == 0, (
            f"field {field!r} should be 0 on empty DB; got {body[field]}"
        )
