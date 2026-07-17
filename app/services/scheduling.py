"""Provider availability service."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Provider, ProviderAvailability

log = get_logger(__name__)


async def set_availability(
    db: AsyncSession,
    provider_id: str,
    target_date: str,
    available: bool,
    slots: list[str] | None = None,
) -> ProviderAvailability:
    """Set availability for a provider on a specific date.

    Creates or updates the record. Validates that the provider exists.
    """
    provider = await db.get(Provider, provider_id)
    if provider is None:
        raise NotFoundError(f"Provider {provider_id} not found")

    # Validate date format
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"Invalid date format '{target_date}'. Use YYYY-MM-DD.") from None

    # Upsert
    stmt = select(ProviderAvailability).where(
        ProviderAvailability.provider_id == provider_id,
        ProviderAvailability.date == target_date,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        existing.available = available
        existing.slots = slots
        await db.commit()
        await db.refresh(existing)
        return existing

    record = ProviderAvailability(
        provider_id=provider_id,
        date=target_date,
        available=available,
        slots=slots,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    log.info("Availability set: provider=%s date=%s available=%s", provider_id, target_date, available)
    return record


async def get_availability(
    db: AsyncSession,
    provider_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[ProviderAvailability]:
    """Get availability for a provider within an optional date range."""
    stmt = (
        select(ProviderAvailability)
        .where(ProviderAvailability.provider_id == provider_id)
        .order_by(ProviderAvailability.date.asc())
    )

    if start_date:
        stmt = stmt.where(ProviderAvailability.date >= start_date)
    if end_date:
        stmt = stmt.where(ProviderAvailability.date <= end_date)

    result = await db.execute(stmt)
    return list(result.scalars().all())
