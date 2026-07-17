"""
Provider endpoints: quotation listing + bidding.
"""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_provider
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Auction, Provider, Quotation
from app.schemas import AuctionCreate, AuctionRead
from app.services import pricing

log = get_logger(__name__)

# Quotation fields that providers CAN see (basic data only)
QUOTATION_BASIC_FIELDS = {
    "id", "client_name", "service_name", "service_type", "service_zone",
    "origin_postal_code", "origin_type", "destination_postal_code",
    "destination_type", "created_at",
}

router = APIRouter(prefix="/quotation", tags=["provider:quotations"])


@router.get(
    "",
    summary="List quotations available for bidding (provider)",
)
async def list_quotations_for_bidding(
    db: AsyncSession = Depends(get_db),
    provider: Provider = Depends(current_provider),
    limit: int = Query(50, ge=1, le=200),
):
    """List quotations in BIDDING state. Each provider sees basic data."""
    stmt = (
        select(Quotation)
        .where(Quotation.state == "BIDDING")
        .order_by(Quotation.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    quotations = result.scalars().all()

    # Return only basic fields
    result_data = []
    for q in quotations:
        data = {k: getattr(q, k, None) for k in QUOTATION_BASIC_FIELDS}
        result_data.append(data)

    return result_data


@router.post(
    "/{quotation_id}/bid",
    response_model=AuctionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a bid for a quotation (provider)",
)
async def submit_bid(
    quotation_id: str,
    body: AuctionCreate,
    db: AsyncSession = Depends(get_db),
    provider: Provider = Depends(current_provider),
) -> AuctionRead:
    """Provider submits their price + notes for a quotation."""
    # Verify quotation exists and is in BIDDING state
    stmt = select(Quotation).where(Quotation.id == quotation_id)
    quotation = (await db.execute(stmt)).scalar_one_or_none()
    if quotation is None:
        raise NotFoundError(f"Quotation {quotation_id} not found")
    if quotation.state != "BIDDING":
        raise ValidationError(f"Quotation is in state '{quotation.state}', not BIDDING")

    # Check provider hasn't already bid on this quotation
    stmt = select(Auction).where(
        Auction.quotation_id == quotation_id,
        Auction.provider_id == provider.id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("You have already submitted a bid for this quotation")

    if body.price_load is None:
        raise ValidationError("price_load is required")

    price = pricing.compute_price(body.price_load)
    auction = Auction(
        quotation_id=quotation_id,
        provider_id=provider.id,
        price_load=price.price_load,
        subtotal=price.subtotal,
        mobbit_fee=price.mobbit_fee,
        iva=price.iva,
        transaction_fee=price.transaction_fee,
        total=price.total,
        state="PENDING",
        provider_note=body.provider_note,
        people=body.people,
        id_truck=body.id_truck,
    )
    db.add(auction)
    await db.commit()
    await db.refresh(auction)
    log.info("Bid created: quotation=%s provider=%s price=%s", quotation_id, provider.id, price.total)
    return AuctionRead.model_validate(auction)
