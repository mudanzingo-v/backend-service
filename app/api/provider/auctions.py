"""
Provider-side auction endpoints.

The provider can:
  - List their own auctions (with state filter)
  - View a single auction
  - Accept / counter-offer an admin-assigned auction (PUT)
  - Decline an admin-assigned auction
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, current_provider
from app.core.database import get_db
from app.core.pagination import set_pagination_headers
from app.schemas import (
    AuctionProviderUpdate,
    AuctionRead,
    Message,
)
from app.services import auction as auction_svc

router = APIRouter(prefix="/auction", tags=["provider:auctions"])


@router.get(
    "",
    response_model=list[AuctionRead],
    summary="List my auctions (provider)",
)
async def list_my_auctions(
    state: Optional[str] = Query(None, description="Filter by state (PENDING, SELECTED, REJECTED, DECLINED)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(current_provider),
) -> list[AuctionRead]:
    """All auctions where `provider_id = me`. The provider_id is taken
    from the JWT (no provider can see another provider's auctions)."""
    items, total = await auction_svc.list_auctions_for_provider_paginated(
        db, user.sub, state=state, limit=limit, offset=offset
    )
    if response is not None:
        set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [AuctionRead.model_validate(a) for a in items]


@router.get(
    "/{auction_id}",
    response_model=AuctionRead,
    summary="Get a single auction (provider)",
)
async def get_my_auction(
    auction_id: str,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(current_provider),
) -> AuctionRead:
    """The provider can only see their own auctions."""
    auction = await auction_svc.get_auction(db, auction_id)
    if auction.provider_id != user.sub:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"Auction {auction_id} not found")
    return AuctionRead.model_validate(auction)


@router.put(
    "/{auction_id}",
    response_model=AuctionRead,
    summary="Accept / counter-offer an auction (provider)",
    description=(
        "The provider reviews the admin's suggested price and either:\n"
        "- Accepts as-is (set `accept_admin_price: true`)\n"
        "- Counter-offers (set `price_load` to the new total)\n\n"
        "Only works on PENDING auctions. Returns 409 otherwise."
    ),
)
async def update_my_auction(
    auction_id: str,
    body: AuctionProviderUpdate,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(current_provider),
) -> AuctionRead:
    auction = await auction_svc.provider_update_auction(
        db, auction_id, user.sub, body
    )
    return AuctionRead.model_validate(auction)


@router.post(
    "/{auction_id}/decline",
    response_model=AuctionRead,
    summary="Decline an admin-assigned auction (provider)",
    description=(
        "The provider refuses the assignment. State → DECLINED. The "
        "auction is hidden from the B2C client's list."
    ),
)
async def decline_my_auction(
    auction_id: str,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(current_provider),
) -> AuctionRead:
    from fastapi import Body as BodyParam
    # Accept an optional note in the body
    note: Optional[str] = None
    try:
        # The body is optional
        pass
    except Exception:
        pass
    auction = await auction_svc.provider_decline_auction(
        db, auction_id, user.sub, note=note
    )
    return AuctionRead.model_validate(auction)
