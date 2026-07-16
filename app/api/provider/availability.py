"""Provider availability endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, current_provider
from app.core.database import get_db
from app.services import scheduling as sched_svc

router = APIRouter(prefix="/availability", tags=["provider:availability"])


@router.post("", status_code=201)
async def set_availability(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    available: bool = Query(True),
    slots: str | None = Query(None, description="Comma-separated time slots, e.g. 09:00,10:00,11:00"),
    db: AsyncSession = Depends(get_db),
    provider: AuthUser = Depends(current_provider),
) -> dict:
    """Set availability for a specific date."""
    slot_list = slots.split(",") if slots else None
    record = await sched_svc.set_availability(
        db, provider.sub, date, available, slots=slot_list
    )
    return {
        "id": record.id,
        "date": record.date,
        "available": record.available,
        "slots": record.slots,
    }


@router.get("")
async def get_availability(
    start_date: str | None = Query(None, description="Start date YYYY-MM-DD"),
    end_date: str | None = Query(None, description="End date YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    provider: AuthUser = Depends(current_provider),
) -> list[dict]:
    """Get availability for a date range."""
    records = await sched_svc.get_availability(db, provider.sub, start_date, end_date)
    return [
        {
            "id": r.id,
            "date": r.date,
            "available": r.available,
            "slots": r.slots,
        }
        for r in records
    ]
