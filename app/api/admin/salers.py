"""
Admin endpoints: Saler CRUD.
"""
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_admin
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.pagination import paginate, set_pagination_headers
from app.models import Saler
from app.schemas import Message, SalerCreate, SalerRead, SalerUpdate


router = APIRouter(prefix="/saler", tags=["admin:salers"])


@router.post(
    "",
    response_model=SalerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a saler",
)
async def create_saler(
    body: SalerCreate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    s = Saler(**body.model_dump())
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return SalerRead.model_validate(s)


@router.get(
    "",
    response_model=list[SalerRead],
    summary="List salers",
)
async def list_salers(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    stmt = select(Saler).order_by(Saler.name)
    items, total = await paginate(db, stmt, limit, offset)
    if response is not None:
        set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [SalerRead.model_validate(r) for r in items]


@router.get(
    "/{saler_id}",
    response_model=SalerRead,
    summary="Get a saler",
)
async def get_saler(
    saler_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    s = await db.get(Saler, saler_id)
    if s is None:
        raise NotFoundError(f"Saler {saler_id} not found")
    return SalerRead.model_validate(s)


@router.put(
    "/{saler_id}",
    response_model=SalerRead,
    summary="Update a saler",
)
async def update_saler(
    saler_id: str,
    body: SalerUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    s = await db.get(Saler, saler_id)
    if s is None:
        raise NotFoundError(f"Saler {saler_id} not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    await db.commit()
    await db.refresh(s)
    return SalerRead.model_validate(s)


@router.delete(
    "/{saler_id}",
    response_model=Message,
    summary="Delete a saler",
)
async def delete_saler(
    saler_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    s = await db.get(Saler, saler_id)
    if s is None:
        raise NotFoundError(f"Saler {saler_id} not found")
    await db.delete(s)
    await db.commit()
    return Message(message=f"Saler {saler_id} deleted")
