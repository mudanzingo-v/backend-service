"""
Admin payments HTTP integration tests.

Four tests for `app/api/admin/payments.py`:
  - `POST /api/admin/quotation/{q_id}/payment/mercadopago`
  - `POST /api/admin/quotation/{q_id}/payment/deposito`
  - `GET /api/admin/quotation/{q_id}/payment/s`
  - `GET /api/admin/payment/{payment_id}`

The MP payment requires a pre-existing Auction (it pulls `amount`
from `auction.total`). The deposit payment takes an explicit amount.

Uses unique quotation/auction IDs per test (uuid4 hex) to avoid
collisions with pollution from prior runs.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Auction, Quotation


def _unique() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture
async def seeded_quotation_and_auction(
    db_session: AsyncSession,
) -> tuple[Quotation, Auction]:
    """A quotation + auction pair, both with unique IDs."""
    u = _unique()
    q = Quotation(
        client_name=u,
        client_phone="+525511111111",
        client_email=f"{u}@example.com",
        origin_postal_code="01000",
        destination_postal_code="03100",
    )
    db_session.add(q)
    await db_session.flush()

    a = Auction(
        quotation_id=q.id,
        provider_id=f"prov-{u}",
        price_load=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        mobbit_fee=Decimal("5.00"),
        iva=Decimal("16.80"),
        transaction_fee=Decimal("6.09"),
        total=Decimal("127.89"),
        state="PENDING",
    )
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return q, a


async def test_create_mp_payment_returns_201_with_amount_from_auction(
    client: AsyncClient,
    seeded_quotation_and_auction: tuple[Quotation, Auction],
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `POST /quotation/{q_id}/payment/mercadopago` with `id_auction`
    creates a Payment record with `amount` pulled from `auction.total`.
    """
    q, a = seeded_quotation_and_auction
    resp = await client.post(
        f"/api/admin/quotation/{q.id}/payment/mercadopago",
        json={"id_auction": a.id},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["quotation_id"] == q.id
    assert body["auction_id"] == a.id
    assert body["type"] == "MERCADOPAGO"
    assert body["state"] == "PENDING"
    assert float(body["amount"]) == 127.89


async def test_create_deposit_payment_returns_201_with_explicit_amount(
    client: AsyncClient,
    seeded_quotation_and_auction: tuple[Quotation, Auction],
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `POST /quotation/{q_id}/payment/deposito` with `amount` and
    `id_auction` creates a Payment with the explicit amount.
    """
    q, a = seeded_quotation_and_auction
    resp = await client.post(
        f"/api/admin/quotation/{q.id}/payment/deposito",
        json={"amount": "500.00", "id_auction": a.id, "reference": "TR-12345"},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["quotation_id"] == q.id
    assert body["type"] == "DEPOSIT"
    assert float(body["amount"]) == 500.00


async def test_list_payments_returns_paginated_results(
    client: AsyncClient,
    seeded_quotation_and_auction: tuple[Quotation, Auction],
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /quotation/{q_id}/payment/s` returns 200 + list + pagination."""
    q, a = seeded_quotation_and_auction
    # Seed a payment so the list is non-empty.
    await client.post(
        f"/api/admin/quotation/{q.id}/payment/deposito",
        json={"amount": "100.00", "id_auction": a.id},
        headers=auth_header(dev_jwt_admin),
    )

    resp = await client.get(
        f"/api/admin/quotation/{q.id}/payment/s?limit=10&offset=0",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    for header in ("X-Total-Count", "X-Limit", "X-Offset", "X-Has-Next"):
        assert header in resp.headers, f"missing pagination header {header!r}"


async def test_get_payment_returns_200_with_body(
    client: AsyncClient,
    seeded_quotation_and_auction: tuple[Quotation, Auction],
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /payment/{id}` returns 200 + matching PaymentRead."""
    q, a = seeded_quotation_and_auction
    create_resp = await client.post(
        f"/api/admin/quotation/{q.id}/payment/deposito",
        json={"amount": "200.00", "id_auction": a.id},
        headers=auth_header(dev_jwt_admin),
    )
    payment_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/admin/payment/{payment_id}",
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["id"] == payment_id
    assert body["type"] == "DEPOSIT"
    assert float(body["amount"]) == 200.00


async def test_create_mp_payment_returns_404_for_invalid_auction(
    client: AsyncClient,
    db_session: AsyncSession,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    from app.models import Quotation
    u = uuid.uuid4().hex[:12]
    q = Quotation(
        client_name=u,
        client_phone="+525511111111",
        client_email=f"{u}@example.com",
        origin_postal_code="01000",
        destination_postal_code="03100",
    )
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)

    resp = await client.post(
        f"/api/admin/quotation/{q.id}/payment/mercadopago",
        json={"id_auction": f"nonexistent-{uuid.uuid4().hex}"},
        headers=auth_header(dev_jwt_admin),
    )
    assert resp.status_code == 404
