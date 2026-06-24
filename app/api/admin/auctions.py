"""
Admin endpoints: Auction management.
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_admin
from app.core.database import get_db
from app.core.pagination import set_pagination_headers
from app.schemas import AuctionRead, AuctionUpdate
from app.services import auction as auction_svc

router = APIRouter(prefix="/quotation/{quotation_id}/provider/{provider_id}/auction",
                   tags=["admin:auctions"])


@router.post(
    "",
    response_model=AuctionRead,
    summary="Create an auction on behalf of a provider",
)
async def create_auction_admin(
    quotation_id: str,
    provider_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    """Reuses the auction service; equivalent to the original `apigw_lambdas_auctions.tf` POST."""
    from app.schemas import AuctionCreate
    auction_body = AuctionCreate(**body)
    return await auction_svc.create_auction(db, quotation_id, provider_id, auction_body)


# Top-level auction CRUD (admin)
top_auction_router = APIRouter(prefix="/auction", tags=["admin:auctions"])


@top_auction_router.get(
    "",
    response_model=list[AuctionRead],
    summary="List all auctions (admin)",
    description=(
        "Global listing of auctions across all quotations and providers. "
        "Supports pagination via `limit` and `offset`, and an optional filter "
        "by `quotation_id`. Sort is by `created_at` desc."
    ),
)
async def list_auctions_admin(
    quotation_id: str | None = Query(
        None, description="Filter by quotation id"
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    items, total = await auction_svc.list_auctions_paginated(
        db, quotation_id=quotation_id, limit=limit, offset=offset
    )
    if response is not None:
        set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [AuctionRead.model_validate(a) for a in items]


@top_auction_router.get(
    "/{auction_id}",
    response_model=AuctionRead,
    summary="Get a single auction",
)
async def get_auction(
    auction_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    a = await auction_svc.get_auction(db, auction_id)
    return AuctionRead.model_validate(a)


@top_auction_router.put(
    "/{auction_id}",
    response_model=AuctionRead,
    summary="Update an auction",
)
async def update_auction(
    auction_id: str,
    body: AuctionUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    a = await auction_svc.update_auction(db, auction_id, body)
    return AuctionRead.model_validate(a)


@top_auction_router.delete(
    "/{auction_id}",
    summary="Delete an auction",
)
async def delete_auction(
    auction_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    await auction_svc.delete_auction(db, auction_id)
    return {"message": f"Auction {auction_id} deleted"}
