"""
B2C catalog endpoints (public read-only).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models import InventoryItem, Product, Service
from app.schemas import (
    InventoryItemRead,
    LocationRead,
    ProductRead,
    ServiceRead,
)
from app.services import copomex

router = APIRouter(tags=["b2c:catalog"])


# ---- Location (postal code lookup) ----
@router.get(
    "/location/{postal_code}",
    response_model=LocationRead,
    summary="Lookup a postal code (proxies to Copomex)",
)
async def get_location(postal_code: str) -> LocationRead:
    """
    Proxies to the Copomex API. Token is read from `COPOMEX_API_TOKEN` env var.
    """
    data = await copomex.lookup_postal_code(postal_code)
    return LocationRead(**data)


# ---- Inventory Items ----
@router.get(
    "/inventory/items",
    response_model=list[InventoryItemRead],
    summary="List all inventory items",
)
async def list_inventory_items(
    db: AsyncSession = Depends(get_db),
) -> list[InventoryItemRead]:
    stmt = select(InventoryItem).order_by(InventoryItem.created_at.desc())
    items = (await db.execute(stmt)).scalars().all()
    return [InventoryItemRead.model_validate(i) for i in items]


@router.get(
    "/inventory/{category_id}/items",
    response_model=list[InventoryItemRead],
    summary="List inventory items in a category",
)
async def list_inventory_items_by_category(
    category_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[InventoryItemRead]:
    stmt = (
        select(InventoryItem)
        .where(InventoryItem.category_id == category_id)
        .order_by(InventoryItem.created_at.desc())
    )
    items = (await db.execute(stmt)).scalars().all()
    return [InventoryItemRead.model_validate(i) for i in items]


# ---- Products ----
@router.get(
    "/products",
    response_model=list[ProductRead],
    summary="List all products",
)
async def list_products(
    db: AsyncSession = Depends(get_db),
) -> list[ProductRead]:
    stmt = select(Product).where(Product.active.is_(True)).order_by(Product.name)
    items = (await db.execute(stmt)).scalars().all()
    return [ProductRead.model_validate(i) for i in items]


# ---- Services ----
@router.get(
    "/services",
    response_model=list[ServiceRead],
    summary="List all services",
)
async def list_services(
    db: AsyncSession = Depends(get_db),
) -> list[ServiceRead]:
    stmt = select(Service).where(Service.active.is_(True)).order_by(Service.name)
    items = (await db.execute(stmt)).scalars().all()
    return [ServiceRead.model_validate(i) for i in items]
