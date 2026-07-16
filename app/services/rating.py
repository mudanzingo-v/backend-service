"""Rating service — B2C clients rate providers after service completion."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Auction, Rating

log = get_logger(__name__)


async def rate_provider(
    db: AsyncSession,
    auction_id: str,
    score: int,
    comment: str | None = None,
) -> Rating:
    """Rate a provider for a completed auction.

    Validates that the auction exists and is in ACCEPTED state (service
    completed). Each auction can only be rated once.
    """
    if score < 1 or score > 5:
        raise ValidationError("Score must be between 1 and 5")

    auction = await db.get(Auction, auction_id)
    if auction is None:
        raise NotFoundError(f"Auction {auction_id} not found")

    if auction.state != "ACCEPTED":
        raise ValidationError(
            f"Cannot rate an auction in state '{auction.state}'. Must be ACCEPTED."
        )

    # Check for existing rating
    stmt = select(Rating).where(Rating.auction_id == auction_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("This auction has already been rated")

    rating = Rating(
        auction_id=auction_id,
        provider_id=auction.provider_id,
        quotation_id=auction.quotation_id,
        score=score,
        comment=comment,
    )
    db.add(rating)
    await db.commit()
    await db.refresh(rating)

    log.info("Rating created: auction=%s provider=%s score=%d", auction_id, auction.provider_id, score)
    return rating


async def get_provider_rating_summary(
    db: AsyncSession, provider_id: str
) -> dict:
    """Get rating summary for a provider."""
    stmt = select(
        func.count(Rating.id),
        func.avg(Rating.score),
    ).where(Rating.provider_id == provider_id)
    result = await db.execute(stmt)
    row = result.one()

    total = row[0] or 0
    avg = float(row[1]) if row[1] else 0.0

    # Score distribution
    stmt = select(Rating.score, func.count(Rating.id)).where(
        Rating.provider_id == provider_id
    ).group_by(Rating.score).order_by(Rating.score)
    result = await db.execute(stmt)
    distribution = {str(row[0]): row[1] for row in result}

    return {
        "total_ratings": total,
        "average_score": round(avg, 1),
        "distribution": distribution,
    }


async def get_auction_rating(
    db: AsyncSession, auction_id: str
) -> Rating | None:
    """Get the rating for a specific auction, if any."""
    stmt = select(Rating).where(Rating.auction_id == auction_id)
    return (await db.execute(stmt)).scalar_one_or_none()
