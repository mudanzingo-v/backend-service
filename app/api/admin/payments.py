"""
Admin endpoints: Payment management.
"""
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_admin
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.pagination import paginate, set_pagination_headers
from app.models import Auction, Payment
from app.schemas import (
    Message,
    PaymentCreateDeposit,
    PaymentCreateMP,
    PaymentRead,
)


quotation_payments_router = APIRouter(
    prefix="/quotation/{quotation_id}/payment", tags=["admin:payments"]
)


@quotation_payments_router.post(
    "/mercadopago",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a MercadoPago payment link for a quotation",
)
async def create_mp_payment(
    quotation_id: str,
    body: PaymentCreateMP,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    """Creates a Payment record (PENDING). The MP preference is created
    separately by the B2C client when they select an auction."""
    auction = await db.get(Auction, body.id_auction)
    if auction is None:
        raise NotFoundError(f"Auction {body.id_auction} not found")
    p = Payment(
        quotation_id=quotation_id,
        auction_id=body.id_auction,
        type="MERCADOPAGO",
        state="PENDING",
        amount=auction.total,
        currency="MXN",
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return PaymentRead.model_validate(p)


@quotation_payments_router.post(
    "/deposito",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a deposit payment",
)
async def create_deposit_payment(
    quotation_id: str,
    body: PaymentCreateDeposit,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    p = Payment(
        quotation_id=quotation_id,
        auction_id=body.id_auction,
        type="DEPOSIT",
        state="PENDING",
        amount=body.amount,
        currency="MXN",
        raw_payload={"reference": body.reference} if body.reference else None,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return PaymentRead.model_validate(p)


@quotation_payments_router.get(
    "/s",
    response_model=list[PaymentRead],
    summary="List payments for a quotation",
)
async def list_payments(
    quotation_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    stmt = (
        select(Payment)
        .where(Payment.quotation_id == quotation_id)
        .order_by(Payment.created_at.desc())
    )
    items, total = await paginate(db, stmt, limit, offset)
    if response is not None:
        set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [PaymentRead.model_validate(r) for r in items]


# Single payment by id
top_payment_router = APIRouter(prefix="/payment", tags=["admin:payments"])


@top_payment_router.get(
    "/{payment_id}",
    response_model=PaymentRead,
    summary="Get a single payment",
)
async def get_payment(
    payment_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    p = await db.get(Payment, payment_id)
    if p is None:
        raise NotFoundError(f"Payment {payment_id} not found")
    return PaymentRead.model_validate(p)
