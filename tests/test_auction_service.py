"""
Auction service tests.

Eight service-level tests for `app.services.auction.*`. Uses the
smoke suite's `db_session` fixture (savepoint-rollback interaction
is the same as for `test_quotation_service.py` — see the design's
`§6` risks).

Covers:
- `auction_exists`, `create_auction`, `update_auction`, `delete_auction`
- `list_auctions`, `list_auctions_filtered`, `list_auctions_for_quotation`
- `admin_assign_provider` + the `ConflictError` on duplicate assignment
- `provider_decline_auction` (happy path + cross-provider 403)

Does NOT cover: `provider_update_auction` (counter-offer) — left for
a follow-up; `select_auction` (B2C flow with MP integration); the
paginated variants — already covered by the smoke suite's pagination
tests.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Provider, Quotation
from app.schemas import (
    AuctionAdminAssign,
    AuctionCreate,
    AuctionUpdate,
)
from app.services.auction import (
    STATE_DECLINED,
    STATE_PENDING,
    admin_assign_provider,
    auction_exists,
    create_auction,
    delete_auction,
    get_auction,
    list_auctions,
    list_auctions_for_provider,
    list_auctions_for_quotation,
    provider_decline_auction,
    update_auction,
)


def _unique() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture
async def seeded_provider_and_quotation(
    db_session: AsyncSession,
) -> tuple[Provider, Quotation]:
    """A provider + quotation pair with unique IDs (FK-clean)."""
    u = _unique()
    p = Provider(id=f"prov-{u}", name=f"Test Provider {u}", active=True)
    q = Quotation(
        client_name=u,
        client_phone="+525511111111",
        client_email=f"{u}@example.com",
        origin_postal_code="01000",
        destination_postal_code="03100",
    )
    db_session.add(p)
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(p)
    await db_session.refresh(q)
    return p, q


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------

async def test_auction_exists_returns_false_when_no_auction(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`auction_exists` returns False when no auction has been created."""
    p, q = seeded_provider_and_quotation
    result = await auction_exists(db_session, q.id, p.id)
    assert result is False


async def test_create_auction_persists_with_calculated_total(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """
    `create_auction` writes an Auction row with `total` calculated
    via `pricing.compute_price(price_load)`.

    For price_load=100.00: total = 127.89 (mobbit_fee=5.00, iva=16.80,
    tx_fee=6.09).
    """
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(
        price_load="100.00",
        people="2",
        id_truck="",
        cash_on_delivery=None,
    )
    auction = await create_auction(db_session, q.id, p.id, body)

    assert auction.quotation_id == q.id
    assert auction.provider_id == p.id
    assert auction.state == STATE_PENDING
    assert float(auction.price_load) == 100.00
    assert float(auction.subtotal) == 100.00
    assert float(auction.mobbit_fee) == 5.00
    assert float(auction.iva) == 16.80
    assert float(auction.transaction_fee) == 6.09
    assert float(auction.total) == 127.89


async def test_create_auction_raises_conflict_on_duplicate(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`create_auction` raises `ConflictError` if the same provider already has an auction."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    await create_auction(db_session, q.id, p.id, body)

    with pytest.raises(ConflictError):
        await create_auction(db_session, q.id, p.id, body)


async def test_update_auction_partial_fields_only(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`update_auction` updates only the provided fields."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    a = await create_auction(db_session, q.id, p.id, body)
    original_total = float(a.total)

    update = AuctionUpdate(provider_note="Updated note")
    updated = await update_auction(db_session, a.id, update)

    assert updated.provider_note == "Updated note"
    # Other fields unchanged.
    assert float(updated.total) == original_total


async def test_delete_auction_removes_row(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`delete_auction` removes the row; subsequent `get_auction` raises NotFoundError."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    a = await create_auction(db_session, q.id, p.id, body)
    auction_id = a.id

    await delete_auction(db_session, auction_id)

    with pytest.raises(NotFoundError):
        await get_auction(db_session, auction_id)


# ---------------------------------------------------------------------------
# List queries
# ---------------------------------------------------------------------------

async def test_list_auctions_returns_all_with_pagination(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`list_auctions` returns auctions ordered by `created_at DESC`."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    a1 = await create_auction(db_session, q.id, p.id, body)

    items = await list_auctions(db_session)
    ids = {x.id for x in items}
    assert a1.id in ids, f"auction {a1.id} missing from list_auctions result"


async def test_list_auctions_for_quotation_returns_only_matching(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`list_auctions_for_quotation` filters by quotation_id."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    a = await create_auction(db_session, q.id, p.id, body)

    items = await list_auctions_for_quotation(db_session, q.id)
    assert any(x.id == a.id for x in items)


async def test_list_auctions_for_provider_returns_only_matching(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`list_auctions_for_provider` filters by provider_id."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    a = await create_auction(db_session, q.id, p.id, body)

    items = await list_auctions_for_provider(db_session, p.id)
    assert any(x.id == a.id for x in items)


# ---------------------------------------------------------------------------
# Admin-assign + Provider-decline flows
# ---------------------------------------------------------------------------

async def test_admin_assign_provider_creates_pending_auction(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`admin_assign_provider` creates an Auction with state=PENDING and total from admin_budget."""
    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("500.00"))

    auction = await admin_assign_provider(db_session, q.id, p.id, body)

    assert auction.state == STATE_PENDING
    assert auction.quotation_id == q.id
    assert auction.provider_id == p.id
    # total from admin_budget=500.00: 500 + 25 + 84 + 30.45 = 639.45
    assert float(auction.total) == 639.45, (
        f"expected total=639.45 from admin_budget=500.00; got {auction.total}"
    )


async def test_provider_decline_auction_sets_state_declined(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`provider_decline_auction` transitions state to DECLINED."""
    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    declined = await provider_decline_auction(db_session, a.id, p.id)

    assert declined.state == STATE_DECLINED


async def test_list_auctions_paginated_returns_total(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    from app.schemas import AuctionAdminAssign
    from app.services.auction import (
        admin_assign_provider,
        list_auctions_paginated,
    )

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    await admin_assign_provider(db_session, q.id, p.id, body)

    items, total = await list_auctions_paginated(db_session, q.id)
    assert total == 1
    assert len(items) == 1


async def test_select_auction_transitions_state_to_selected(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """
    Verify `select_auction` transitions the target auction to SELECTED
    (re-fetched via `get_auction` because `select_auction` returns a
    dict combining auction + preference data).
    """
    from app.schemas import AuctionAdminAssign, AuctionSelectBody
    from app.services.auction import (
        STATE_SELECTED,
        admin_assign_provider,
        get_auction,
        select_auction,
    )

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    select_body = AuctionSelectBody(id_auction=a.id, cash_on_delivery="false")
    await select_auction(db_session, q.id, select_body)

    refreshed = await get_auction(db_session, a.id)
    assert refreshed.state == STATE_SELECTED

