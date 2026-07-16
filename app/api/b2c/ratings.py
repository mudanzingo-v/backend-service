"""B2C rating endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import rating as rating_svc

router = APIRouter(prefix="/api/b2c", tags=["b2c:ratings"])


@router.post("/auction/{auction_id}/rate", status_code=201)
async def rate_auction(
    auction_id: str,
    score: int,
    comment: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rate a provider for a completed auction (score 1-5)."""
    rating = await rating_svc.rate_provider(db, auction_id, score, comment)
    return {
        "id": rating.id,
        "auction_id": rating.auction_id,
        "score": rating.score,
        "comment": rating.comment,
    }
