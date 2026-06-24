"""
Admin endpoints: Provider + Truck CRUD.
"""
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_admin
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.pagination import paginate, set_pagination_headers
from app.models import Provider, Truck
from app.schemas import (
    ProviderRead,
    ProviderUpdate,
    TruckCreate,
    TruckRead,
    TruckUpdate,
)

# ---- Providers ----
providers_router = APIRouter(prefix="/provider", tags=["admin:providers"])


@providers_router.post(
    "",
    response_model=ProviderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a provider",
)
async def create_provider(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    """`id` is the Cognito sub — provided by the admin when creating."""
    p = Provider(**body)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return ProviderRead.model_validate(p)


@providers_router.get(
    "",
    response_model=list[ProviderRead],
    summary="List providers",
)
async def list_providers(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    # Exclude synthetic providers (no name) created during the DDB→PG migration
    stmt = (
        select(Provider)
        .where(Provider.name.is_not(None))
        .order_by(Provider.name)
    )
    items, total = await paginate(db, stmt, limit, offset)
    if response is not None:
        set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [ProviderRead.model_validate(r) for r in items]


@providers_router.get(
    "/{provider_id}",
    response_model=ProviderRead,
    summary="Get a provider",
)
async def get_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    p = await db.get(Provider, provider_id)
    if p is None:
        raise NotFoundError(f"Provider {provider_id} not found")
    # Block access to synthetic providers (those with no name)
    if p.name is None:
        raise NotFoundError(f"Provider {provider_id} not found")
    return ProviderRead.model_validate(p)


@providers_router.put(
    "/{provider_id}",
    response_model=ProviderRead,
    summary="Update a provider",
)
async def update_provider(
    provider_id: str,
    body: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    p = await db.get(Provider, provider_id)
    if p is None:
        raise NotFoundError(f"Provider {provider_id} not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return ProviderRead.model_validate(p)


# ---- Provider Trucks ----
trucks_router = APIRouter(
    prefix="/provider/{provider_id}/truck", tags=["admin:providers"]
)


@trucks_router.post(
    "",
    response_model=TruckRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a truck for a provider",
)
async def create_truck(
    provider_id: str,
    body: TruckCreate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    # Verify provider exists
    p = await db.get(Provider, provider_id)
    if p is None:
        raise NotFoundError(f"Provider {provider_id} not found")
    t = Truck(provider_id=provider_id, **body.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return TruckRead.model_validate(t)


@trucks_router.get(
    "",
    response_model=list[TruckRead],
    summary="List a provider's trucks",
)
async def list_trucks(
    provider_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    stmt = select(Truck).where(Truck.provider_id == provider_id).order_by(Truck.created_at.desc())
    items, total = await paginate(db, stmt, limit, offset)
    if response is not None:
        set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [TruckRead.model_validate(r) for r in items]


@trucks_router.get(
    "/{truck_id}",
    response_model=TruckRead,
    summary="Get a single truck",
)
async def get_truck(
    provider_id: str,
    truck_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    t = await db.get(Truck, truck_id)
    if t is None or t.provider_id != provider_id:
        raise NotFoundError(f"Truck {truck_id} not found for provider {provider_id}")
    return TruckRead.model_validate(t)


@trucks_router.put(
    "/{truck_id}",
    response_model=TruckRead,
    summary="Update a truck",
)
async def update_truck(
    provider_id: str,
    truck_id: str,
    body: TruckUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    t = await db.get(Truck, truck_id)
    if t is None or t.provider_id != provider_id:
        raise NotFoundError(f"Truck {truck_id} not found for provider {provider_id}")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    await db.commit()
    await db.refresh(t)
    return TruckRead.model_validate(t)
