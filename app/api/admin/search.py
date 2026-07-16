"""Admin search endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import QuotationRead
from app.services.search import search_quotations

router = APIRouter(prefix="/search", tags=["admin:search"])


@router.get("/quotations", response_model=list[QuotationRead])
async def search_q(
    q: str = Query("", description="Search query (name, phone, email, address, ID)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[QuotationRead]:
    """Full-text search across quotations."""
    results = await search_quotations(db, q, limit=limit, offset=offset)
    return [QuotationRead.model_validate(r) for r in results]
