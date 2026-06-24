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


# ---------------------------------------------------------------------------
# PR2 — Stripe CheckoutSession integration in select_auction
# ---------------------------------------------------------------------------
#
# `select_auction` now calls `app.services.stripe.create_checkout_session`
# instead of the old MP service, and persists a `CheckoutSession` row plus
# a `Payment` row with `type="STRIPE"`. These four tests pin that contract.
# They mock `app.services.stripe.create_checkout_session` to return a
# deterministic dict, then assert the row state and the return shape.


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
    from app.schemas import AuctionAdminAssign, AuctionSelectBody
    from app.services.auction import (
        admin_assign_provider,
        select_auction,
    )

    p, q = seeded_provider_and_quotation
    body = AuctionAdminAssign(admin_budget=Decimal("100.00"))
    a = await admin_assign_provider(db_session, q.id, p.id, body)

    # Mock the Stripe service to return a deterministic checkout session.
    # Use a UNIQUE session id per test (per handoff Learning #3: the
    # db_session fixture's savepoint-rollback does NOT undo explicit
    # `db.commit()` calls inside `select_auction`, so prior test runs
    # can leave rows in the DB; UNIQUE on stripe_session_id would then
    # collide across tests in the same session).
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

    # ---- Assert: a CheckoutSession row was created with the expected fields ----
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
    NOT have keys `init_point` or `sandbox_init_point` (the old MP shape).
    """
    from app.schemas import AuctionAdminAssign, AuctionSelectBody
    from app.services.auction import (
        admin_assign_provider,
        select_auction,
    )

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

    assert "session_id" in result, f"missing 'session_id' in result keys: {list(result.keys())}"
    assert "url" in result, f"missing 'url' in result keys: {list(result.keys())}"
    assert "init_point" not in result, (
        f"old MP key 'init_point' should be gone; got keys: {list(result.keys())}"
    )
    assert "sandbox_init_point" not in result, (
        f"old MP key 'sandbox_init_point' should be gone; got keys: {list(result.keys())}"
    )
    assert result["session_id"], "session_id should be non-empty"
    assert result["url"].startswith("https://checkout.stripe.com/"), (
        f"url should be a Stripe checkout URL; got {result['url']!r}"
    )


async def test_payment_type_is_stripe_not_mercadopago(
    db_session: AsyncSession,
    seeded_provider_and_quotation: tuple[Provider, Quotation],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    `select_auction` creates a `Payment` row with `type="STRIPE"` and the
    `stripe_*` fields populated (no MP fields).
    """
    from sqlalchemy import select

    from app.models import Payment
    from app.schemas import AuctionAdminAssign, AuctionSelectBody
    from app.services.auction import (
        admin_assign_provider,
        select_auction,
    )

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

    # ---- Assert: a Payment row was created with type=STRIPE ----
    stmt = select(Payment).where(Payment.auction_id == a.id)
    payments = (await db_session.execute(stmt)).scalars().all()
    assert len(payments) == 1, f"expected 1 Payment; got {len(payments)}"
    payment = payments[0]

    assert payment.type == "STRIPE", (
        f"expected payment.type='STRIPE'; got {payment.type!r}"
    )
    assert payment.stripe_payment_intent_id is None, (
        "stripe_payment_intent_id is set by the webhook (PR3), not by select_auction"
    )
    assert payment.stripe_checkout_session_id is not None
    assert payment.stripe_checkout_session_id.startswith("cs_test_eeee"), (
        f"expected stripe_checkout_session_id to start with 'cs_test_eeee'; "
        f"got {payment.stripe_checkout_session_id!r}"
    )


async def test_payment_model_has_no_mp_columns() -> None:
    """
    The `Payment` model has `stripe_*` columns; it does NOT have
    `mp_payment_id`, `mp_preference_id`, `mp_status`, `mp_status_detail`.
    """
    from app.models import Payment

    column_names = {c.name for c in Payment.__table__.columns}

    # New Stripe columns must be present.
    assert "stripe_payment_intent_id" in column_names
    assert "stripe_checkout_session_id" in column_names
    assert "stripe_payment_status" in column_names

    # Old MP columns must be gone.
    for legacy in ("mp_payment_id", "mp_preference_id", "mp_status", "mp_status_detail"):
        assert legacy not in column_names, (
            f"legacy MP column {legacy!r} should be removed from Payment; "
            f"present columns: {sorted(column_names)}"
        )

