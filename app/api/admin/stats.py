"""
Stats endpoint — aggregate counts for the admin dashboard.

Single SQL query, single round trip. Returns counts for every entity.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import Stats

router = APIRouter(prefix="/stats", tags=["admin:stats"])


@router.get(
    "",
    response_model=Stats,
    summary="Aggregate counts for the admin dashboard",
)
async def get_stats(db: AsyncSession = Depends(get_db)) -> Stats:
    """Returns the row count of every entity in a single query.

    Used by the backoffice's dashboard cards. Single round-trip so the
    dashboard loads fast even with a large DB.
    """
    result = await db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM quotations
                 WHERE client_email != 'synthetic@orphan.local') AS quotations,
                (SELECT COUNT(*) FROM auctions)              AS auctions,
                (SELECT COUNT(*) FROM products)              AS products,
                (SELECT COUNT(*) FROM services)              AS services,
                (SELECT COUNT(*) FROM inventory_items)       AS inventory_items,
                (SELECT COUNT(*) FROM inventory_categories
                 WHERE name NOT LIKE '%synthetic%')           AS inventory_categories,
                (SELECT COUNT(*) FROM providers
                 WHERE name IS NOT NULL)                     AS providers,
                (SELECT COUNT(*) FROM salers)                AS salers,
                (SELECT COUNT(*) FROM payments)              AS payments,
                (SELECT COUNT(*) FROM trucks)                AS trucks
        """)
    )
    row = result.one()
    return Stats(**row._mapping)
