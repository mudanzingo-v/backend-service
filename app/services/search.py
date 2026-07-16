"""Full-text search service for quotations using PostgreSQL tsvector."""
from __future__ import annotations

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Quotation


async def search_quotations(
    db: AsyncSession,
    query: str,
    limit: int = 50,
    offset: int = 0,
) -> list[Quotation]:
    """Search quotations by name, phone, email, address, or ID.

    Uses PostgreSQL full-text search (tsvector) when available, falls
    back to ILIKE for simple matching.
    """
    if not query or not query.strip():
        stmt = (
            select(Quotation)
            .where(Quotation.client_email != "synthetic@orphan.local")
            .order_by(Quotation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    search_term = f"%{query.strip()}%"

    stmt = (
        select(Quotation)
        .where(
            Quotation.client_email != "synthetic@orphan.local",
            or_(
                Quotation.id.ilike(search_term),
                Quotation.client_name.ilike(search_term),
                Quotation.client_phone.ilike(search_term),
                Quotation.client_email.ilike(search_term),
                Quotation.origin_adress.ilike(search_term),
                Quotation.destination_adress.ilike(search_term),
                Quotation.origin_postal_code.ilike(search_term),
                Quotation.destination_postal_code.ilike(search_term),
            ),
        )
        .order_by(Quotation.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
