"""
Admin quotations HTTP integration tests — `req-admin-quotations-coverage-001`.

Eight integration tests that exercise `app/api/admin/quotations.py`
endpoints via the in-process ASGI client. Each test creates the
precondition state via the service layer (to keep the HTTP surface
honest) and asserts on the HTTP response contract (status code,
headers, body shape).

Auth: all endpoints require `current_admin`; tests use the smoke
suite's `dev_jwt_admin` fixture via the `auth_header` factory.

Isolation: each test uses a unique email prefix (uuid4 hex prefix) so
that list_quotations pollution from prior runs cannot break count
assertions. Quotation/service-state assertions use exact IDs to
side-step pollution entirely.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Provider
from app.schemas import QuotationCreateAdmin
from app.services.quotation import (
    ST_DRAFT,
    ST_QUOTED,
    create_quotation_admin,
    publish_quotation,
)


def _unique_email() -> str:
    """Generate a unique email per test run to avoid pollution collisions."""
    return f"q-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture
def admin_quotation_body() -> QuotationCreateAdmin:
    """Admin quotation body with a unique email per call."""
    return QuotationCreateAdmin(
        client_name="Admin HTTP Test",
        client_phone="+525511111111",
        client_email=_unique_email(),
        origin_postal_code="01000",
        destination_postal_code="03100",
        origin_adress="Av. Reforma 123",
        destination_adress="Av. Insurgentes Sur 456",
    )


# ---------------------------------------------------------------------------
# Endpoint scenarios
# ---------------------------------------------------------------------------

async def test_list_quotations_returns_paginated_results_with_headers(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_quotation_body: QuotationCreateAdmin,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `GET /api/admin/quotation?limit=2&offset=0` with admin auth returns:
      - HTTP 200
      - JSON list of length ≤ 2
      - pagination headers X-Total-Count, X-Limit, X-Offset, X-Has-Next
    """
    # Seed at least 3 quotations so pagination has something to do.
    for _ in range(3):
        body = QuotationCreateAdmin(
            client_name=_unique_email(),
            client_phone="+525511111111",
            client_email=_unique_email(),
            origin_postal_code="01000",
            destination_postal_code="03100",
        )
        await create_quotation_admin(db_session, body)

    resp = await client.get(
        "/api/admin/quotation?limit=2&offset=0",
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) <= 2, f"expected ≤ 2 items, got {len(body)}"
    # Pagination headers MUST all be present.
    for header in ("X-Total-Count", "X-Limit", "X-Offset", "X-Has-Next"):
        assert header in resp.headers, (
            f"missing pagination header {header!r}; headers={dict(resp.headers)}"
        )
    assert resp.headers["X-Limit"] == "2"
    assert resp.headers["X-Offset"] == "0"


async def test_create_quotation_admin_returns_201_with_body(
    client: AsyncClient,
    admin_quotation_body: QuotationCreateAdmin,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `POST /api/admin/quotation` with a full body returns 201 + a
    `QuotationRead` JSON with all fields populated and `state="DRAFT"`.
    """
    resp = await client.post(
        "/api/admin/quotation",
        json=admin_quotation_body.model_dump(mode="json"),
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["client_email"] == admin_quotation_body.client_email
    assert body["client_name"] == admin_quotation_body.client_name
    assert body["state"] == ST_DRAFT
    assert "id" in body and body["id"]


async def test_get_quotation_returns_200_with_body(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_quotation_body: QuotationCreateAdmin,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """`GET /api/admin/quotation/{q_id}` returns 200 + matching QuotationRead."""
    created = await create_quotation_admin(db_session, admin_quotation_body)

    resp = await client.get(
        f"/api/admin/quotation/{created.id}",
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["id"] == created.id
    assert body["client_email"] == admin_quotation_body.client_email


async def test_update_quotation_returns_200_with_updated_body(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_quotation_body: QuotationCreateAdmin,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `PUT /api/admin/quotation/{q_id}` with only `client_phone` updates
    only that field; other fields unchanged.
    """
    created = await create_quotation_admin(db_session, admin_quotation_body)
    original_email = created.client_email

    resp = await client.put(
        f"/api/admin/quotation/{created.id}",
        json={"client_phone": "+525599999999"},
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["client_phone"] == "+525599999999"
    assert body["client_email"] == original_email


async def test_delete_quotation_returns_200_with_message(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_quotation_body: QuotationCreateAdmin,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `DELETE /api/admin/quotation/{q_id}` returns 200 + `Message`
    containing "deleted" and the id.
    """
    created = await create_quotation_admin(db_session, admin_quotation_body)

    resp = await client.delete(
        f"/api/admin/quotation/{created.id}",
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert "message" in body
    assert "deleted" in body["message"].lower()
    assert created.id in body["message"]


async def test_publish_quotation_via_endpoint_returns_200_with_quoted_state(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_quotation_body: QuotationCreateAdmin,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `POST /api/admin/quotation/{q_id}/publish` transitions DRAFT → QUOTED
    and the change persists (subsequent GET confirms).
    """
    created = await create_quotation_admin(db_session, admin_quotation_body)

    resp = await client.post(
        f"/api/admin/quotation/{created.id}/publish",
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["state"] == ST_QUOTED

    # Subsequent GET confirms persistence.
    get_resp = await client.get(
        f"/api/admin/quotation/{created.id}",
        headers=auth_header(dev_jwt_admin),
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["state"] == ST_QUOTED


async def test_cancel_quotation_via_endpoint_returns_200_with_cancelled_state(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_quotation_body: QuotationCreateAdmin,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `POST /api/admin/quotation/{q_id}/cancel` transitions to CANCELLED.
    """
    created = await create_quotation_admin(db_session, admin_quotation_body)
    # First publish (so cancel is meaningful; non-terminal → CANCELLED).
    await publish_quotation(db_session, created.id)

    resp = await client.post(
        f"/api/admin/quotation/{created.id}/cancel",
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 200, (
        f"expected 200; got {resp.status_code} body={resp.text!r}"
    )
    body = resp.json()
    assert body["state"] == "CANCELLED"


async def test_assign_provider_creates_pending_auction_returns_201(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_quotation_body: QuotationCreateAdmin,
    dev_jwt_admin: str,
    auth_header: Callable[[str], dict[str, str]],
) -> None:
    """
    `POST /api/admin/quotation/{q_id}/assign-provider?provider_id={p_id}`
    creates an Auction with state=PENDING and returns 201 + AuctionRead.
    """
    # Set up: a quotation + a provider.
    created = await create_quotation_admin(db_session, admin_quotation_body)
    provider = Provider(
        id=f"prov-{uuid.uuid4().hex[:12]}",
        name="Test Provider",
        email=_unique_email(),
        phone="+525588888888",
        rfc="TEST010101ABC",
        active=True,
    )
    db_session.add(provider)
    await db_session.commit()
    await db_session.refresh(provider)

    resp = await client.post(
        f"/api/admin/quotation/{created.id}/assign-provider?provider_id={provider.id}",
        json={"admin_budget": "100.00"},
        headers=auth_header(dev_jwt_admin),
    )

    assert resp.status_code == 201, (
        f"expected 201; got {resp.status_code} body={resp.text!r}"
    )
    body: dict[str, Any] = resp.json()
    assert body["state"] == "PENDING"
    assert body["quotation_id"] == created.id
    assert body["provider_id"] == provider.id
    # Total is calculated from admin_budget=100.00 via compute_price.
    # mobbit_fee=5.00, iva=16.80, tx_fee=6.09 → total=127.89.
    assert float(body["total"]) == 127.89, (
        f"expected total=127.89 from admin_budget=100.00; got {body['total']}"
    )
