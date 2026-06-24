"""
Admin endpoints: Quotation management + provider assignment.

This is the "admin selects provider" workflow:
  1. Admin views a quotation detail.
  2. Admin picks a provider and sets `admin_budget` (the price they think
     the work is worth).
  3. Backend creates a new Auction with state=PENDING and the price
     calculated from admin_budget.
  4. The provider sees the assignment in their app and can accept, counter
     or decline.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_admin
from app.core.database import get_db
from app.core.pagination import paginate, set_pagination_headers
from app.schemas import (
    AuctionAdminAssign,
    AuctionRead,
    Message,
    QuotationCreateAdmin,
    QuotationRead,
    QuotationUpdate,
)
from app.services import auction as auction_svc
from app.services.quotation import ST_QUOTED


router = APIRouter(prefix="/quotation", tags=["admin:quotations"])


@router.get(
    "",
    response_model=list[QuotationRead],
    summary="List quotations (admin)",
)
async def list_quotations(
    state: Optional[str] = Query(None, description="Filter by state"),
    q: Optional[str] = Query(None, description="Search by client name, email, phone, service name, or postal code"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
) -> list[QuotationRead]:
    from sqlalchemy import select, or_
    from app.models import Quotation
    stmt = select(Quotation).where(Quotation.client_email != "synthetic@orphan.local").order_by(Quotation.created_at.desc())
    if state is not None:
        stmt = stmt.where(Quotation.state == state)
    if q is not None and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Quotation.client_name.ilike(term),
                Quotation.client_email.ilike(term),
                Quotation.client_phone.ilike(term),
                Quotation.service_name.ilike(term),
                Quotation.origin_postal_code.ilike(term),
                Quotation.destination_postal_code.ilike(term),
            )
        )
    items, total = await paginate(db, stmt, limit, offset)
    if response is not None:
        set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [QuotationRead.model_validate(q) for q in items]


@router.post(
    "",
    response_model=QuotationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a quotation (admin)",
)
async def create_quotation(
    body: QuotationCreateAdmin,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
) -> QuotationRead:
    from app.services.quotation import create_quotation_admin
    q = await create_quotation_admin(db, body)
    return QuotationRead.model_validate(q)


@router.get(
    "/{quotation_id}",
    response_model=QuotationRead,
    summary="Get a single quotation",
)
async def get_quotation(
    quotation_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
) -> QuotationRead:
    from app.services.quotation import get_quotation as svc
    q = await svc(db, quotation_id)
    return QuotationRead.model_validate(q)


@router.put(
    "/{quotation_id}",
    response_model=QuotationRead,
    summary="Update a quotation",
)
async def update_quotation(
    quotation_id: str,
    body: QuotationUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
) -> QuotationRead:
    from app.services.quotation import update_quotation as svc
    q = await svc(db, quotation_id, body)
    return QuotationRead.model_validate(q)


@router.delete(
    "/{quotation_id}",
    response_model=Message,
    summary="Delete a quotation (admin)",
)
async def delete_quotation(
    quotation_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
) -> Message:
    from app.services.quotation import delete_quotation as svc
    await svc(db, quotation_id)
    return Message(message=f"Quotation {quotation_id} deleted")


@router.post(
    "/{quotation_id}/publish",
    response_model=QuotationRead,
    status_code=status.HTTP_200_OK,
    summary="Publish a quotation (DRAFT → QUOTED)",
)
async def publish_quotation(
    quotation_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
) -> QuotationRead:
    from app.services.quotation import publish_quotation as svc
    q = await svc(db, quotation_id)
    return QuotationRead.model_validate(q)


@router.post(
    "/{quotation_id}/cancel",
    response_model=QuotationRead,
    status_code=status.HTTP_200_OK,
    summary="Cancel a quotation",
)
async def cancel_quotation(
    quotation_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
) -> QuotationRead:
    from app.services.quotation import cancel_quotation as svc
    q = await svc(db, quotation_id)
    return QuotationRead.model_validate(q)


# ============================================================================
# Provider assignment (the new "Select provider" workflow)
# ============================================================================
assign_provider_router = APIRouter(
    prefix="/quotation/{quotation_id}", tags=["admin:quotations"]
)


@assign_provider_router.post(
    "/assign-provider",
    response_model=AuctionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a provider to a quotation (with admin budget)",
    description=(
        "Creates a new Auction with state=PENDING. The `provider_id` comes "
        "in the body. The `admin_budget` is the price the admin sets. The "
        "provider can then accept, counter-offer, or decline.\n\n"
        "Returns 409 if the provider already has an auction for this quotation."
    ),
)
async def assign_provider(
    quotation_id: str,
    body: AuctionAdminAssign,
    provider_id: str = Query(..., description="The provider to assign"),
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
) -> AuctionRead:
    from app.models import Provider
    # Validate provider exists
    p = await db.get(Provider, provider_id)
    if p is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"Provider {provider_id} not found")

    auction = await auction_svc.admin_assign_provider(
        db, quotation_id, provider_id, body
    )
    return AuctionRead.model_validate(auction)
