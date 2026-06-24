"""
B2C quotation endpoints (public).
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import (
    QuotationCreateB2C,
    QuotationRead,
    QuotationUpdate,
)
from app.services import quotation as quotation_svc

router = APIRouter(prefix="/quotation", tags=["b2c:quotations"])


@router.post(
    "",
    response_model=QuotationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a public quotation (B2C lead)",
)
async def create_quotation(
    body: QuotationCreateB2C,
    db: AsyncSession = Depends(get_db),
) -> QuotationRead:
    """
    Public endpoint. The client only submits their contact info.
    The full quotation (addresses, services, items) is filled in by
    the admin via the RCCM API.
    """
    q = await quotation_svc.create_quotation_b2c(db, body)
    return QuotationRead.model_validate(q)


@router.get(
    "/{quotation_id}",
    response_model=QuotationRead,
    summary="Get a single quotation",
)
async def get_quotation(
    quotation_id: str,
    db: AsyncSession = Depends(get_db),
) -> QuotationRead:
    q = await quotation_svc.get_quotation(db, quotation_id)
    return QuotationRead.model_validate(q)


@router.put(
    "/{quotation_id}",
    response_model=QuotationRead,
    summary="Update a quotation (B2C)",
)
async def update_quotation(
    quotation_id: str,
    body: QuotationUpdate,
    db: AsyncSession = Depends(get_db),
) -> QuotationRead:
    q = await quotation_svc.update_quotation(db, quotation_id, body)
    return QuotationRead.model_validate(q)
