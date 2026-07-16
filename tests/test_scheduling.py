"""Scheduling tests."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Provider
from app.services import scheduling as sched_svc


@pytest.fixture
async def seeded_provider(db_session: AsyncSession) -> Provider:
    p = Provider(id=str(uuid.uuid4()), name="Sched Provider", active=True)
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def test_set_availability_creates_record(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """`set_availability` creates a new availability record."""
    record = await sched_svc.set_availability(
        db_session, seeded_provider.id, "2026-07-20", True,
        slots=["09:00", "10:00", "11:00"],
    )
    assert record.date == "2026-07-20"
    assert record.available is True
    assert record.slots == ["09:00", "10:00", "11:00"]
    assert record.provider_id == seeded_provider.id


async def test_set_availability_updates_existing(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """`set_availability` updates an existing record (upsert)."""
    await sched_svc.set_availability(db_session, seeded_provider.id, "2026-07-20", True)
    await sched_svc.set_availability(db_session, seeded_provider.id, "2026-07-20", False)

    records = await sched_svc.get_availability(db_session, seeded_provider.id)
    assert len(records) == 1
    assert records[0].available is False


async def test_set_availability_invalid_date_raises_validation(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """Invalid date format raises ValidationError."""
    with pytest.raises(ValidationError):
        await sched_svc.set_availability(db_session, seeded_provider.id, "not-a-date", True)


async def test_set_availability_nonexistent_provider_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """Non-existent provider raises NotFoundError."""
    with pytest.raises(NotFoundError):
        await sched_svc.set_availability(db_session, "nonexistent", "2026-07-20", True)


async def test_get_availability_returns_filtered(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """`get_availability` filters by date range."""
    await sched_svc.set_availability(db_session, seeded_provider.id, "2026-07-20", True)
    await sched_svc.set_availability(db_session, seeded_provider.id, "2026-07-21", True)

    records = await sched_svc.get_availability(
        db_session, seeded_provider.id, start_date="2026-07-21", end_date="2026-07-21"
    )
    assert len(records) == 1
    assert records[0].date == "2026-07-21"
