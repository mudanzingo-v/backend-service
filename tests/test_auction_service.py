"""
Auction service tests — `req-auction-coverage-001`.

Twenty-five+ service-level tests for `app.services.auction.*`. Uses the
smoke suite's `db_session` fixture (savepoint-rollback interaction
is the same as for `test_quotation_service.py`).

Covers:
- Core CRUD: `create_auction`, `get_auction`, `update_auction`, `delete_auction`
- List queries: `list_auctions`, `list_auctions_filtered`, `list_auctions_for_quotation`,
  `list_auctions_for_provider`, `list_auctions_for_provider_paginated`
- Admin assign + provider decline flows
- `provider_update_auction` (accept, counter-offer, note-only, error paths)
- `select_auction` edge cases (COD, provider_id match, missing quotation, no PENDING)
- Stripe CheckoutSession integration
- Error paths: NotFoundError, ConflictError, ForbiddenError, ValidationError
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import Provider, Quotation
from app.schemas import (
    AuctionAdminAssign,
    AuctionCreate,
    AuctionUpdate,
)
from app.services.auction import (
    STATE_DECLINED,
    STATE_PENDING,
    STATE_SELECTED,
    admin_assign_provider,
    auction_exists,
    create_auction,
    delete_auction,
    get_auction,
    list_auctions,
    list_auctions_filtered,
    list_auctions_for_provider,
    list_auctions_for_provider_paginated,
    list_auctions_for_quotation,
    list_auctions_paginated,
    provider_decline_auction,
    provider_update_auction,
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


# =============================================================================
# Core CRUD
# =============================================================================

async def test_auction_exists_returns_false_when_no_auction(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`auction_exists` returns False when no auction has been created."""
    p, q = seeded_provider_and_quotation
    result = await auction_exists(db_session, q.id, p.id)
    assert result is False


async def test_auction_exists_returns_true_when_exists(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`auction_exists` returns True when an auction exists for the pair."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    await create_auction(db_session, q.id, p.id, body)

    result = await auction_exists(db_session, q.id, p.id)
    assert result is True


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


async def test_create_auction_invalid_price_raises_validation_error(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`create_auction` raises ValidationError when price_load is not a valid Decimal."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="not-a-number", people="1", id_truck="")
    with pytest.raises(ValidationError) as exc_info:
        await create_auction(db_session, q.id, p.id, body)
    assert "Invalid price_load" in str(exc_info.value)


async def test_get_auction_happy_path(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`get_auction` returns the auction by id."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    a = await create_auction(db_session, q.id, p.id, body)

    fetched = await get_auction(db_session, a.id)
    assert fetched.id == a.id
    assert fetched.state == STATE_PENDING


async def test_get_auction_nonexistent_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """`get_auction` raises NotFoundError for a non-existent id."""
    with pytest.raises(NotFoundError):
        await get_auction(db_session, "nonexistent-id")


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


async def test_update_auction_nonexistent_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """`update_auction` raises NotFoundError for a non-existent id."""
    update = AuctionUpdate(provider_note="irrelevant")
    with pytest.raises(NotFoundError):
        await update_auction(db_session, "nonexistent-id", update)


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


async def test_delete_auction_nonexistent_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """`delete_auction` raises NotFoundError for a non-existent id."""
    with pytest.raises(NotFoundError):
        await delete_auction(db_session, "nonexistent-id")


# =============================================================================
# List queries
# =============================================================================

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


async def test_list_auctions_filtered_without_quotation_id_returns_all(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`list_auctions_filtered` with `quotation_id=None` returns all auctions."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    a = await create_auction(db_session, q.id, p.id, body)

    items = await list_auctions_filtered(db_session, quotation_id=None)
    assert any(x.id == a.id for x in items)


async def test_list_auctions_filtered_with_quotation_id(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`list_auctions_filtered` with a quotation_id filters by that quotation."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    a = await create_auction(db_session, q.id, p.id, body)

    items = await list_auctions_filtered(db_session, quotation_id=q.id)
    assert any(x.id == a.id for x in items)


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


async def test_list_auctions_for_provider_with_state_filter(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`list_auctions_for_provider` with a non-matching state returns empty."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    await create_auction(db_session, q.id, p.id, body)

    items = await list_auctions_for_provider(db_session, p.id, state="SELECTED")
    assert items == [], f"expected empty list for non-matching state; got {len(items)} items"


async def test_list_auctions_for_provider_paginated_returns_total(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`list_auctions_for_provider_paginated` returns items + total count."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    await create_auction(db_session, q.id, p.id, body)

    items, total = await list_auctions_for_provider_paginated(db_session, p.id)
    assert total == 1
    assert len(items) == 1


async def test_list_auctions_for_provider_paginated_with_state(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`list_auctions_for_provider_paginated` filters by state."""
    p, q = seeded_provider_and_quotation
    body = AuctionCreate(price_load="100.00", people="1", id_truck="")
    await create_auction(db_session, q.id, p.id, body)

    items, total = await list_auctions_for_provider_paginated(
        db_session, p.id, state="NONEXISTENT"
    )
    assert total == 0
    assert items == []


# =============================================================================
# Admin-assign + Provider-decline flows (extended)
# =============================================================================

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


async def test_admin_assign_provider_raises_conflict_on_duplicate(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`admin_assign_provider` raises ConflictError if the provider already has an auction."""
    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    await admin_assign_provider(db_session, q.id, p.id, body)

    with pytest.raises(ConflictError):
        await admin_assign_provider(db_session, q.id, p.id, body)


async def test_admin_assign_provider_with_people_and_note(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`admin_assign_provider` stores people, truck, and note when provided."""
    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(
        admin_budget=Decimal("200.00"),
        people="3",
        id_truck="truck-001",
        note="Please handle with care",
    )
    auction = await admin_assign_provider(db_session, q.id, p.id, body)

    assert auction.state == STATE_PENDING
    assert auction.people == "3"
    assert auction.id_truck == "truck-001"
    assert auction.provider_note == "Please handle with care"
    assert float(auction.total) > 0


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


async def test_provider_decline_auction_with_note(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`provider_decline_auction` saves the optional note."""
    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    declined = await provider_decline_auction(db_session, a.id, p.id, note="Not interested")
    assert declined.state == STATE_DECLINED
    assert declined.provider_note == "Not interested"


async def test_provider_decline_auction_nonexistent_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """`provider_decline_auction` raises NotFoundError for non-existent auction."""
    with pytest.raises(NotFoundError):
        await provider_decline_auction(db_session, "nonexistent", "any-provider")


async def test_provider_decline_auction_wrong_provider_raises_forbidden(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`provider_decline_auction` raises ForbiddenError when the wrong provider tries."""
    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    with pytest.raises(ForbiddenError):
        await provider_decline_auction(db_session, a.id, "wrong-provider")


async def test_provider_decline_auction_from_selected_raises_conflict(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`provider_decline_auction` raises ConflictError when auction is not PENDING."""
    from sqlalchemy import update as sa_update
    from app.models import Auction as AuctionModel

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)
    # Manually set state to SELECTED (simulates B2C selection before provider acts)
    await db_session.execute(
        sa_update(AuctionModel).where(AuctionModel.id == a.id).values(state="SELECTED")
    )
    await db_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        await provider_decline_auction(db_session, a.id, p.id)
    assert "Cannot decline" in str(exc_info.value)


async def test_list_auctions_paginated_returns_total(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))

    p, q = seeded_provider_and_quotation
    await admin_assign_provider(db_session, q.id, p.id, body)

    items, total = await list_auctions_paginated(db_session, q.id)
    assert total == 1
    assert len(items) == 1


# =============================================================================
# select_auction — state transition
# =============================================================================

async def test_select_auction_transitions_state_to_selected(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """
    Verify `select_auction` transitions the target auction to SELECTED.
    """
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    select_body = AuctionSelectBody(id_auction=a.id, cash_on_delivery="false")
    await select_auction(db_session, q.id, select_body)

    refreshed = await get_auction(db_session, a.id)
    assert refreshed.state == STATE_SELECTED


async def test_select_auction_cash_on_delivery_uses_cod_pricing(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    `select_auction` with `cash_on_delivery=true` uses COD pricing breakdown.
    """
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    async def fake_create_checkout_session(**_: object) -> dict:
        sid = f"cs_test_cod{uuid.uuid4().hex[:8]}"
        return {
            "id": sid,
            "url": f"https://checkout.stripe.com/c/pay/{sid}",
            "status": "open",
            "payment_status": "unpaid",
            "amount_total": 10000,
            "currency": "mxn",
        }

    monkeypatch.setattr(
        "app.services.stripe.create_checkout_session", fake_create_checkout_session
    )

    select_body = AuctionSelectBody(id_auction=a.id, cash_on_delivery="true")
    await select_auction(db_session, q.id, select_body)

    refreshed = await get_auction(db_session, a.id)
    assert refreshed.state == STATE_SELECTED
    assert refreshed.cash_on_delivery_provider is not None
    assert refreshed.cash_on_delivery_mobbit is not None
    # price_load=100.00, COD: provider=100.00, mobbit=100.00*1.15=115.00
    assert float(refreshed.cash_on_delivery_provider) == 100.00
    assert float(refreshed.cash_on_delivery_mobbit) == 115.00


async def test_select_auction_selects_by_provider_id(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    `select_auction` can match the auction via `provider_id`.
    """
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    async def fake_create_checkout_session(**_: object) -> dict:
        sid = f"cs_test_prov{uuid.uuid4().hex[:8]}"
        return {
            "id": sid,
            "url": f"https://checkout.stripe.com/c/pay/{sid}",
            "status": "open",
            "payment_status": "unpaid",
            "amount_total": 12789,
            "currency": "mxn",
        }

    monkeypatch.setattr(
        "app.services.stripe.create_checkout_session", fake_create_checkout_session
    )

    # Select by provider_id instead of auction id
    select_body = AuctionSelectBody(id_auction=p.id, cash_on_delivery="false")
    await select_auction(db_session, q.id, select_body)

    refreshed = await get_auction(db_session, a.id)
    assert refreshed.state == STATE_SELECTED


async def test_select_auction_unknown_auction_id_raises_not_found(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`select_auction` raises NotFoundError when the auction_id doesn't match any PENDING auction in the quotation."""
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    p, q = seeded_provider_and_quotation
    # Create an auction for a DIFFERENT provider so the quotation HAS a PENDING auction
    # but the requested id_auction doesn't match it.
    other_prov = Provider(id=f"other-{_unique()}", name="Other Provider", active=True)
    db_session.add(other_prov)
    await db_session.commit()
    await db_session.refresh(other_prov)

    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    await admin_assign_provider(db_session, q.id, other_prov.id, body)

    async def fake_create_checkout_session(**_: object) -> dict:
        sid = f"cs_test_unk{uuid.uuid4().hex[:8]}"
        return {"id": sid, "url": f"https://checkout.stripe.com/c/pay/{sid}", "status": "open", "payment_status": "unpaid", "amount_total": 12789, "currency": "mxn"}

    monkeypatch.setattr(
        "app.services.stripe.create_checkout_session", fake_create_checkout_session
    )

    # Pass non-matching id_auction
    select_body = AuctionSelectBody(id_auction="completely-wrong", cash_on_delivery="false")
    with pytest.raises(NotFoundError) as exc_info:
        await select_auction(db_session, q.id, select_body)
    assert "not found in this quotation" in str(exc_info.value)


async def test_select_auction_missing_quotation_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """`select_auction` raises NotFoundError when the quotation doesn't exist."""
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    select_body = AuctionSelectBody(id_auction="some-auction", cash_on_delivery="false")
    with pytest.raises(NotFoundError):
        await select_auction(db_session, "nonexistent-quotation", select_body)


async def test_select_auction_no_pending_raises_not_found(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`select_auction` raises NotFoundError when no PENDING auctions exist."""
    from sqlalchemy import update as sa_update
    from app.models import Auction as AuctionModel
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)
    # Force the auction to DECLINED so no PENDING auctions exist
    await db_session.execute(
        sa_update(AuctionModel).where(AuctionModel.id == a.id).values(state="DECLINED")
    )
    await db_session.commit()

    select_body = AuctionSelectBody(id_auction=a.id, cash_on_delivery="false")
    with pytest.raises(NotFoundError) as exc_info:
        await select_auction(db_session, q.id, select_body)
    assert "No PENDING auctions" in str(exc_info.value)


async def test_select_auction_no_pending_for_quotation_without_auctions(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`select_auction` raises NotFoundError when the quotation has no auctions at all."""
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    _, q = seeded_provider_and_quotation

    select_body = AuctionSelectBody(id_auction="nonexistent-auction", cash_on_delivery="false")
    with pytest.raises(NotFoundError) as exc_info:
        await select_auction(db_session, q.id, select_body)
    assert "No PENDING auctions" in str(exc_info.value)


# =============================================================================
# provider_update_auction
# =============================================================================

async def test_provider_update_auction_accept_admin_price_no_change(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """
    `provider_update_auction` with `accept_admin_price=True` and no new
    `price_load` keeps the existing price and updates the note.
    """
    from app.schemas import AuctionProviderUpdate

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)
    original_total = float(a.total)

    update = AuctionProviderUpdate(accept_admin_price=True, provider_note="I'll take it")
    updated = await provider_update_auction(db_session, a.id, p.id, update)

    assert updated.provider_note == "I'll take it"
    assert float(updated.total) == original_total, "price should remain unchanged"


async def test_provider_update_auction_counter_offer_recalculates(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """
    `provider_update_auction` with a new `price_load` recalculates the price
    breakdown.
    """
    from app.schemas import AuctionProviderUpdate

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    # Counter-offer with a higher price
    update = AuctionProviderUpdate(price_load="200.00")
    updated = await provider_update_auction(db_session, a.id, p.id, update)

    # price_load=200.00: 200 + 10 + 33.60 + 12.18 = 255.78
    assert float(updated.price_load) == 200.00
    assert float(updated.total) == 255.78


async def test_provider_update_auction_updates_people_and_truck(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """
    `provider_update_auction` updates `people` and `id_truck` when provided.
    """
    from app.schemas import AuctionProviderUpdate

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    update = AuctionProviderUpdate(people="3", id_truck="truck-999")
    updated = await provider_update_auction(db_session, a.id, p.id, update)

    assert updated.people == "3"
    assert updated.id_truck == "truck-999"


async def test_provider_update_auction_wrong_provider_raises_forbidden(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`provider_update_auction` raises ForbiddenError when the wrong provider tries."""
    from app.schemas import AuctionProviderUpdate

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    update = AuctionProviderUpdate(accept_admin_price=True)
    with pytest.raises(ForbiddenError):
        await provider_update_auction(db_session, a.id, "wrong-provider", update)


async def test_provider_update_auction_wrong_state_raises_conflict(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`provider_update_auction` raises ConflictError when auction is not PENDING."""
    from sqlalchemy import update as sa_update
    from app.models import Auction as AuctionModel
    from app.schemas import AuctionProviderUpdate

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)
    # Force state to SELECTED
    await db_session.execute(
        sa_update(AuctionModel).where(AuctionModel.id == a.id).values(state="SELECTED")
    )
    await db_session.commit()

    update = AuctionProviderUpdate(accept_admin_price=True)
    with pytest.raises(ConflictError) as exc_info:
        await provider_update_auction(db_session, a.id, p.id, update)
    assert "Cannot update" in str(exc_info.value)


async def test_provider_update_auction_invalid_price_raises_validation(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
) -> None:
    """`provider_update_auction` raises ValidationError for invalid price_load."""
    from app.schemas import AuctionProviderUpdate

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    update = AuctionProviderUpdate(price_load="not-a-number")
    with pytest.raises(ValidationError) as exc_info:
        await provider_update_auction(db_session, a.id, p.id, update)
    assert "Invalid price_load" in str(exc_info.value)


async def test_provider_update_auction_nonexistent_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """`provider_update_auction` raises NotFoundError for non-existent auction."""
    from app.schemas import AuctionProviderUpdate

    update = AuctionProviderUpdate(accept_admin_price=True)
    with pytest.raises(NotFoundError):
        await provider_update_auction(db_session, "nonexistent", "some-provider", update)


# =============================================================================
# Stripe CheckoutSession integration in select_auction
# =============================================================================

async def test_select_auction_creates_checkout_session_row(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    `select_auction` calls `app.services.stripe.create_checkout_session` with
    `amount_cents=12789` AND `currency="mxn"`; a `checkout_sessions` row
    exists with `amount_total=12789`, `currency="mxn"`.
    """
    from sqlalchemy import select

    from app.models import CheckoutSession
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    fake_session_id = f"cs_test_aaaa{uuid.uuid4().hex[:8]}"
    fake_url = f"https://checkout.stripe.com/c/pay/{fake_session_id}"

    async def fake_create_checkout_session(
        *,
        auction_id: str,
        provider_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        assert amount_cents == 12789, f"expected 12789 cents (127.89 MXN); got {amount_cents}"
        assert currency == "mxn", f"expected currency='mxn'; got {currency!r}"
        assert metadata is not None
        assert metadata.get("auction_id") == a.id
        return {
            "id": fake_session_id,
            "url": fake_url,
            "status": "open",
            "payment_status": "unpaid",
            "amount_total": amount_cents,
            "currency": currency,
        }

    monkeypatch.setattr(
        "app.services.stripe.create_checkout_session", fake_create_checkout_session
    )

    select_body = AuctionSelectBody(id_auction=a.id, cash_on_delivery="false")
    await select_auction(db_session, q.id, select_body)

    stmt = select(CheckoutSession).where(CheckoutSession.auction_id == a.id)
    sessions = (await db_session.execute(stmt)).scalars().all()
    assert len(sessions) == 1, f"expected 1 CheckoutSession; got {len(sessions)}"
    s = sessions[0]
    assert s.stripe_session_id == fake_session_id
    assert s.url == fake_url
    assert s.amount_total == 12789
    assert s.currency == "mxn"
    assert s.status == "open"
    assert s.payment_status == "unpaid"


async def test_select_auction_returns_session_url_not_init_point(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    `select_auction` returns a dict with `session_id` and `url` keys; does
    NOT have MP keys.
    """
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    async def fake_create_checkout_session(
        **_kwargs: object,
    ) -> dict:
        sid = f"cs_test_cccc{uuid.uuid4().hex[:8]}"
        return {
            "id": sid,
            "url": f"https://checkout.stripe.com/c/pay/{sid}",
            "status": "open",
            "payment_status": "unpaid",
            "amount_total": 12789,
            "currency": "mxn",
        }

    monkeypatch.setattr(
        "app.services.stripe.create_checkout_session", fake_create_checkout_session
    )

    select_body = AuctionSelectBody(id_auction=a.id, cash_on_delivery="false")
    result = await select_auction(db_session, q.id, select_body)

    assert "session_id" in result
    assert "url" in result
    assert "init_point" not in result
    assert "sandbox_init_point" not in result


async def test_select_auction_creates_stripe_payment(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    `select_auction` creates a `Payment` row with `type="STRIPE"`.
    """
    from sqlalchemy import select

    from app.models import Payment
    from app.schemas import AuctionSelectBody
    from app.services.auction import select_auction

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    async def fake_create_checkout_session(
        **_kwargs: object,
    ) -> dict:
        sid = f"cs_test_eeee{uuid.uuid4().hex[:8]}"
        return {
            "id": sid,
            "url": f"https://checkout.stripe.com/c/pay/{sid}",
            "status": "open",
            "payment_status": "unpaid",
            "amount_total": 12789,
            "currency": "mxn",
        }

    monkeypatch.setattr(
        "app.services.stripe.create_checkout_session", fake_create_checkout_session
    )

    select_body = AuctionSelectBody(id_auction=a.id, cash_on_delivery="false")
    await select_auction(db_session, q.id, select_body)

    stmt = select(Payment).where(Payment.auction_id == a.id)
    payments = (await db_session.execute(stmt)).scalars().all()
    assert len(payments) == 1
    payment = payments[0]
    assert payment.type == "STRIPE"


async def test_payment_model_has_no_mp_columns() -> None:
    """
    The `Payment` model has `stripe_*` columns; it does NOT have MP columns.
    """
    from app.models import Payment

    column_names = {c.name for c in Payment.__table__.columns}

    assert "stripe_payment_intent_id" in column_names
    assert "stripe_checkout_session_id" in column_names
    assert "stripe_payment_status" in column_names

    for legacy in ("mp_payment_id", "mp_preference_id", "mp_status", "mp_status_detail"):
        assert legacy not in column_names
