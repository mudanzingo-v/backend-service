"""
Auction service — providers submit offers, clients select one.

State machine for auctions (Phase 2.3, 2026-06-17):

  PENDING ──┬──► SELECTED  (B2C client picks this one)
            └──► REJECTED   (B2C client picks another, or admin cancels)
            └──► DECLINED   (provider refuses the admin's assignment)

  Admin flow:
    1. Admin assigns a provider to a quotation with `admin_budget`.
    2. System creates an Auction with state=PENDING and the price
       calculated from admin_budget.
    3. Provider sees the auction in their app.
    4. Provider can:
       - Accept as-is (no change to the price)
       - Counter-offer (set their own price)
       - Decline (state → DECLINED)

  B2C client sees only PENDING auctions (filtered out DECLINED + REJECTED).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import Auction, Payment, Preference, Quotation
from app.schemas import (
    AuctionAdminAssign,
    AuctionCreate,
    AuctionProviderUpdate,
    AuctionSelectBody,
    AuctionUpdate,
)
from app.services import mercadopago, pricing

# State constants
STATE_PENDING = "PENDING"
STATE_SELECTED = "SELECTED"
STATE_REJECTED = "REJECTED"
STATE_DECLINED = "DECLINED"
STATE_ACCEPTED = "ACCEPTED"
STATE_PAID = "PAID"

ALL_STATES = {
    STATE_PENDING, STATE_SELECTED, STATE_REJECTED,
    STATE_DECLINED, STATE_ACCEPTED, STATE_PAID,
}


# =============================================================================
# Existing flows (kept for compatibility)
# =============================================================================
async def auction_exists(
    db: AsyncSession, quotation_id: str, provider_id: str
) -> bool:
    stmt = select(Auction).where(
        Auction.quotation_id == quotation_id,
        Auction.provider_id == provider_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def create_auction(
    db: AsyncSession,
    quotation_id: str,
    provider_id: str,
    body: AuctionCreate,
) -> Auction:
    if await auction_exists(db, quotation_id, provider_id):
        raise ConflictError("Auction already exists for this provider and quotation")

    cash_on_delivery = (body.cash_on_delivery or "").lower() == "true"
    try:
        price = Decimal(body.price_load)
    except Exception as e:
        raise ValidationError(f"Invalid price_load: {body.price_load}") from e

    breakdown = pricing.compute_price(price, cash_on_delivery=cash_on_delivery)
    return await _persist_new_auction(
        db, quotation_id, provider_id, breakdown,
        people=body.people, id_truck=body.id_truck,
        cash_on_delivery=cash_on_delivery,
        services=body.services, products=body.products,
    )


async def update_auction(
    db: AsyncSession, auction_id: str, body: AuctionUpdate
) -> Auction:
    auction = await db.get(Auction, auction_id)
    if auction is None:
        raise NotFoundError(f"Auction {auction_id} not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(auction, k, v)
    await db.commit()
    await db.refresh(auction)
    return auction


async def delete_auction(db: AsyncSession, auction_id: str) -> None:
    auction = await db.get(Auction, auction_id)
    if auction is None:
        raise NotFoundError(f"Auction {auction_id} not found")
    await db.delete(auction)
    await db.commit()


async def list_auctions(
    db: AsyncSession, limit: int = 100, offset: int = 0
) -> list[Auction]:
    stmt = select(Auction).order_by(Auction.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_auctions_filtered(
    db: AsyncSession,
    quotation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Auction]:
    stmt = select(Auction).order_by(Auction.created_at.desc()).limit(limit).offset(offset)
    if quotation_id is not None:
        stmt = stmt.where(Auction.quotation_id == quotation_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_auctions_for_quotation(
    db: AsyncSession, quotation_id: str
) -> list[Auction]:
    """All auctions for a given quotation, oldest first (matches the original B2C flow)."""
    stmt = (
        select(Auction)
        .where(Auction.quotation_id == quotation_id)
        .order_by(Auction.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_auction(db: AsyncSession, auction_id: str) -> Auction:
    auction = await db.get(Auction, auction_id)
    if auction is None:
        raise NotFoundError(f"Auction {auction_id} not found")
    return auction


# =============================================================================
# New flows: admin assign + provider accept/decline
# =============================================================================
async def admin_assign_provider(
    db: AsyncSession,
    quotation_id: str,
    provider_id: str,
    body: AuctionAdminAssign,
) -> Auction:
    """
    Admin assigns a provider to a quotation with a suggested price.

    Creates a new Auction with state=PENDING. If the provider already
    has an auction for this quotation, returns 409.
    """
    if await auction_exists(db, quotation_id, provider_id):
        raise ConflictError("Auction already exists for this provider and quotation")

    breakdown = pricing.compute_price(body.admin_budget, cash_on_delivery=False)

    auction = await _persist_new_auction(
        db, quotation_id, provider_id, breakdown,
        people=body.people, id_truck=body.id_truck,
        admin_budget=body.admin_budget,
        provider_note=body.note,
    )
    return auction


async def provider_update_auction(
    db: AsyncSession,
    auction_id: str,
    provider_id: str,
    body: AuctionProviderUpdate,
) -> Auction:
    """
    Provider accepts / counter-offers an admin-assigned auction.

    - If `accept_admin_price=True` and `price_load` is None, confirm
      the existing price (no change).
    - If `price_load` is set, recalculate the price breakdown.
    - If state is not PENDING, raise 409 (already SELECTED/REJECTED/DECLINED).
    """
    auction = await db.get(Auction, auction_id)
    if auction is None:
        raise NotFoundError(f"Auction {auction_id} not found")
    if auction.provider_id != provider_id:
        raise ForbiddenError("This auction doesn't belong to you")
    if auction.state != STATE_PENDING:
        raise ConflictError(
            f"Cannot update auction in state '{auction.state}'"
        )

    # Accept as-is: just update note if provided
    if body.provider_note is not None:
        auction.provider_note = body.provider_note

    if body.accept_admin_price and body.price_load is None:
        # No price change, just confirming
        pass
    elif body.price_load is not None:
        try:
            new_price = Decimal(body.price_load)
        except Exception as e:
            raise ValidationError(f"Invalid price_load: {body.price_load}") from e
        breakdown = pricing.compute_price(new_price, cash_on_delivery=False)
        auction.price_load = breakdown.price_load
        auction.subtotal = breakdown.subtotal
        auction.mobbit_fee = breakdown.mobbit_fee
        auction.iva = breakdown.iva
        auction.transaction_fee = breakdown.transaction_fee
        auction.total = breakdown.total
    # else: just a note update, no price change

    if body.people is not None:
        auction.people = body.people
    if body.id_truck is not None:
        auction.id_truck = body.id_truck

    await db.commit()
    await db.refresh(auction)
    return auction


async def provider_decline_auction(
    db: AsyncSession,
    auction_id: str,
    provider_id: str,
    note: str | None = None,
) -> Auction:
    """
    Provider declines an admin-assigned auction. State → DECLINED.

    The B2C client and the admin will not see this auction in the
    "available" lists.
    """
    auction = await db.get(Auction, auction_id)
    if auction is None:
        raise NotFoundError(f"Auction {auction_id} not found")
    if auction.provider_id != provider_id:
        raise ForbiddenError("This auction doesn't belong to you")
    if auction.state != STATE_PENDING:
        raise ConflictError(
            f"Cannot decline an auction in state '{auction.state}'"
        )

    auction.state = STATE_DECLINED
    if note is not None:
        auction.provider_note = note
    await db.commit()
    await db.refresh(auction)
    return auction


async def list_auctions_for_provider(
    db: AsyncSession,
    provider_id: str,
    state: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Auction]:
    """All auctions for a given provider. Used by the provider app."""
    stmt = (
        select(Auction)
        .where(Auction.provider_id == provider_id)
        .order_by(Auction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if state is not None:
        stmt = stmt.where(Auction.state == state)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---- Paginated variants (Phase 3.3) ----
async def list_auctions_paginated(
    db: AsyncSession,
    quotation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Auction], int]:
    """Paginated version of `list_auctions_filtered`."""
    from app.core.pagination import paginate
    stmt = select(Auction).order_by(Auction.created_at.desc())
    if quotation_id is not None:
        stmt = stmt.where(Auction.quotation_id == quotation_id)
    return await paginate(db, stmt, limit, offset)


async def list_auctions_for_provider_paginated(
    db: AsyncSession,
    provider_id: str,
    state: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Auction], int]:
    """Paginated version of `list_auctions_for_provider`."""
    from app.core.pagination import paginate
    stmt = (
        select(Auction)
        .where(Auction.provider_id == provider_id)
        .order_by(Auction.created_at.desc())
    )
    if state is not None:
        stmt = stmt.where(Auction.state == state)
    return await paginate(db, stmt, limit, offset)


# =============================================================================
# Helpers
# =============================================================================
async def _persist_new_auction(
    db: AsyncSession,
    quotation_id: str,
    provider_id: str,
    breakdown: pricing.PriceBreakdown,
    people: str | None = None,
    id_truck: str | None = None,
    cash_on_delivery: bool = False,
    admin_budget: Decimal | None = None,
    provider_note: str | None = None,
    services: list | None = None,
    products: list | None = None,
) -> Auction:
    """Persist a new Auction with state=PENDING. Shared by the legacy
    create_auction and the new admin_assign_provider flows."""
    auction = Auction(
        quotation_id=quotation_id,
        provider_id=provider_id,
        price_load=breakdown.price_load,
        subtotal=breakdown.subtotal,
        mobbit_fee=breakdown.mobbit_fee,
        iva=breakdown.iva,
        transaction_fee=breakdown.transaction_fee,
        total=breakdown.total,
        cash_on_delivery_provider=breakdown.cash_on_delivery_provider,
        cash_on_delivery_mobbit=breakdown.cash_on_delivery_mobbit,
        people=people,
        id_truck=id_truck,
        state=STATE_PENDING,
        admin_budget=admin_budget,
        provider_note=provider_note,
        services=[s.model_dump() for s in services] if services else None,
        products=[p.model_dump() for p in products] if products else None,
    )
    db.add(auction)
    await db.commit()
    await db.refresh(auction)
    return auction


# =============================================================================
# B2C selection (unchanged)
# =============================================================================
async def select_auction(
    db: AsyncSession,
    quotation_id: str,
    body: AuctionSelectBody,
) -> dict[str, Any]:
    """
    B2C client picks one auction. The chosen auction goes to `SELECTED`,
    the rest to `REJECTED`. Then we create a MercadoPago preference.
    """
    quotation = await db.get(Quotation, quotation_id)
    if quotation is None:
        raise NotFoundError(f"Quotation {quotation_id} not found")

    # Only PENDING auctions can be selected (excludes DECLINED)
    all_auctions = await list_auctions_for_quotation(db, quotation_id)
    auctions = [a for a in all_auctions if a.state == STATE_PENDING]
    if not auctions:
        raise NotFoundError("No PENDING auctions for the provided quotation")

    cash_on_delivery = body.cash_on_delivery.lower() == "true"

    selected: Auction | None = None
    for a in auctions:
        if a.id == body.id_auction or a.provider_id == body.id_auction:
            selected = a
            break
    if selected is None:
        raise NotFoundError(f"Auction {body.id_auction} not found in this quotation")

    for a in auctions:
        a.state = STATE_SELECTED if a.id == selected.id else STATE_REJECTED
    await db.flush()

    if cash_on_delivery:
        breakdown = pricing.compute_price(
            Decimal(selected.price_load), cash_on_delivery=True
        )
        selected.cash_on_delivery_provider = breakdown.cash_on_delivery_provider
        selected.cash_on_delivery_mobbit = breakdown.cash_on_delivery_mobbit

    mp_response = await mercadopago.create_preference(
        quotation, selected, cash_on_delivery=cash_on_delivery
    )

    pref = Preference(
        auction_id=selected.id,
        mp_id=str(mp_response.get("id")) if mp_response.get("id") else None,
        init_point=mp_response.get("init_point"),
        sandbox_init_point=mp_response.get("sandbox_init_point"),
        date_created=mp_response.get("date_created"),
        client_id=str(mp_response.get("client_id")) if mp_response.get("client_id") else None,
        collector_id=str(mp_response.get("collector_id")) if mp_response.get("collector_id") else None,
        operation_type=mp_response.get("operation_type"),
        items=str(mp_response.get("items")) if mp_response.get("items") else None,
        payer=str(mp_response.get("payer")) if mp_response.get("payer") else None,
        shipment=str(mp_response.get("shipments")) if mp_response.get("shipments") else None,
    )
    db.add(pref)

    payment = Payment(
        quotation_id=quotation.id,
        auction_id=selected.id,
        type="MERCADOPAGO",
        state=STATE_PENDING,
        amount=Decimal(selected.total) if not cash_on_delivery else (
            Decimal(selected.cash_on_delivery_mobbit or 0)
            + Decimal(selected.cash_on_delivery_provider or 0)
        ),
        currency="MXN",
        mp_preference_id=pref.mp_id,
    )
    db.add(payment)

    await db.commit()
    await db.refresh(pref)
    await db.refresh(payment)

    return {
        "preference_id": pref.id,
        "mp_id": pref.mp_id,
        "init_point": pref.init_point,
        "sandbox_init_point": pref.sandbox_init_point,
        "date_created": pref.date_created,
        "client_id": pref.client_id,
        "collector_id": pref.collector_id,
        "operation_type": pref.operation_type,
        "items": pref.items,
        "payer": pref.payer,
        "shipment": pref.shipment,
        "payment_id": payment.id,
    }
