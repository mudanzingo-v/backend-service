"""
Admin endpoints: Invoice management (CFDI).
"""
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_admin
from app.core.database import get_db
from app.core.pagination import paginate, set_pagination_headers
from app.models import Invoice
from app.schemas.cfdi import InvoiceRead

router = APIRouter(prefix="/invoice", tags=["admin:invoices"])


@router.get(
    "",
    response_model=list[InvoiceRead],
    summary="List all invoices (admin)",
)
async def list_invoices(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    stmt = select(Invoice).order_by(Invoice.created_at.desc())
    items, total = await paginate(db, stmt, limit, offset)
    if response is not None:
        set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [InvoiceRead.model_validate(r) for r in items]
