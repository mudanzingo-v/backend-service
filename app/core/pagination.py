"""
Pagination helpers.

The body of list endpoints stays as `list[T]` (non-breaking for existing
consumers). The pagination metadata is set as response headers:

  X-Total-Count: total number of items (across all pages)
  X-Limit:       the limit used for this request
  X-Offset:      the offset used for this request
  X-Has-Next:    "true" if there are more items after this page

The front reads these headers to render pagination controls.
"""
from __future__ import annotations

from fastapi import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def paginate(
    db: AsyncSession,
    stmt,
    limit: int,
    offset: int,
) -> tuple[list, int]:
    """
    Execute a `SELECT` with `limit`/`offset` and return (items, total).

    The `stmt` should be a `select(Model)` query. We strip any existing
    `limit`/`offset` from it (in case the caller already added them) and
    do a separate `COUNT(*)` for the total.

    Example:
        stmt = select(Quotation).order_by(Quotation.created_at.desc())
        items, total = await paginate(db, stmt, limit=50, offset=0)
    """
    # COUNT(*) without the order_by, limit, offset
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one() or 0

    # Items with limit/offset
    items_stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(items_stmt)
    items = list(result.scalars().all())
    return items, int(total)


def set_pagination_headers(
    response: Response,
    *,
    total: int,
    limit: int,
    offset: int,
) -> None:
    """Set the standard pagination headers on a Response object."""
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    response.headers["X-Has-Next"] = "true" if (offset + limit) < total else "false"
