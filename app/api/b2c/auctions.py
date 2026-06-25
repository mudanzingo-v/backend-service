"""
B2C auction endpoints.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.schemas import (
    AuctionRead,
    AuctionSelectBody,
)
from app.services import auction as auction_svc
from app.services import quotation as quotation_svc

router = APIRouter(prefix="/quotation/{quotation_id}/auction", tags=["b2c:auctions"])


@router.get(
    "/s",
    response_model=list[AuctionRead],
    summary="List auctions for a quotation (B2C)",
)
async def list_auctions(
    quotation_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[AuctionRead]:
    """All auctions submitted for a quotation. NOTE: original filter
    `state = "FILLED"` was on quotations, not auctions; we just return
    all auctions for the quotation here."""
    auctions = await quotation_svc.list_auctions_for_quotation(db, quotation_id)
    return [AuctionRead.model_validate(a) for a in auctions]


@router.put(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Select an auction (B2C) — creates an MP preference",
)
async def select_auction(
    quotation_id: str,
    body: AuctionSelectBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    The B2C client picks one auction. This:
    1. Transitions the chosen auction to SELECTED, all others to REJECTED.
    2. Creates a Stripe Checkout Session.
    3. Creates a Payment record (state = PENDING).

    Returns the Checkout Session (so the client can redirect to its `url`).
    """
    return await auction_svc.select_auction(db, quotation_id, body)


# Sub-route: list auctions (singular vs plural in original API)
quotation_auctions_router = APIRouter(prefix="/quotation/{quotation_id}", tags=["b2c:auctions"])


@quotation_auctions_router.get(
    "/auctions",
    response_model=list[AuctionRead],
    summary="List auctions for a quotation (alt path)",
)
async def list_auctions_alt(
    quotation_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[AuctionRead]:
    """Alternate path matching the original `GET /quotation/{id}/auctions`."""
    auctions = await quotation_svc.list_auctions_for_quotation(db, quotation_id)
    return [AuctionRead.model_validate(a) for a in auctions]


# Top-level route: GET /quotationauctions (the original B2C list)
root_router = APIRouter(prefix="", tags=["b2c:auctions"])


@root_router.get(
    "/quotationauctions",
    response_model=list[AuctionRead],
    summary="List all auctions (B2C top-level)",
)
async def list_all_auctions(
    db: AsyncSession = Depends(get_db),
) -> list[AuctionRead]:
    return [AuctionRead.model_validate(a) for a in await auction_svc.list_auctions(db)]


# ---- CheckoutSession (Stripe) ----
checkout_session_router = APIRouter(
    prefix="/quotation/{quotation_id}/auction/{auction_id}",
    tags=["b2c:auctions"],
)


@checkout_session_router.get(
    "/checkout-session",
    response_model=dict,
    summary="Get the Stripe Checkout Session for a given auction",
)
async def get_checkout_session(
    quotation_id: str,
    auction_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Returns the most recent Checkout Session for this auction."""
    from sqlalchemy import select

    from app.models import CheckoutSession

    stmt = (
        select(CheckoutSession)
        .where(CheckoutSession.auction_id == auction_id)
        .order_by(CheckoutSession.created_at.desc())
        .limit(1)
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        raise NotFoundError("No checkout session yet.")
    return {
        "id_auction": auction_id,
        "id": session.stripe_session_id,
        "url": session.url,
        "client_id": session.stripe_session_id,
        "date_created": session.created_at.isoformat() if session.created_at else None,
        "payer": None,
    }
