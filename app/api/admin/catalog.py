"""
Admin endpoints: Catalog CRUD (products, services, inventory categories, inventory items).
"""
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_admin
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models import InventoryCategory, InventoryItem, Product, Service
from app.schemas import (
    InventoryCategoryCreate,
    InventoryCategoryRead,
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
    Message,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    ServiceCreate,
    ServiceRead,
    ServiceUpdate,
)


# Generic CRUD factory -------------------------------------------------------
def _make_crud_routes(
    router: APIRouter,
    model: type,
    create_schema,
    update_schema,
    read_schema,
    path_prefix: str,
    list_limit_default: int = 100,
):
    @router.post(
        "",
        response_model=read_schema,
        status_code=status.HTTP_201_CREATED,
        summary=f"Create a {model.__name__}",
    )
    async def _create(
        body: create_schema,
        db: AsyncSession = Depends(get_db),
        _admin: object = Depends(current_admin),
    ):
        obj = model(**body.model_dump())
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return read_schema.model_validate(obj)

    @router.get(
        "",
        response_model=list[read_schema],
        summary=f"List {model.__name__}s",
    )
    async def _list(
        limit: int = list_limit_default,
        offset: int = 0,
        response: Response = None,
        db: AsyncSession = Depends(get_db),
        _admin: object = Depends(current_admin),
    ):
        from app.core.pagination import paginate, set_pagination_headers
        stmt = select(model).order_by(getattr(model, "created_at", getattr(model, "name", None)).desc() if hasattr(model, "created_at") else getattr(model, "name"))
        items, total = await paginate(db, stmt, limit, offset)
        if response is not None:
            set_pagination_headers(response, total=total, limit=limit, offset=offset)
        return [read_schema.model_validate(r) for r in items]

    @router.get(
        "/{item_id}",
        response_model=read_schema,
        summary=f"Get a single {model.__name__}",
    )
    async def _get(
        item_id: str,
        db: AsyncSession = Depends(get_db),
        _admin: object = Depends(current_admin),
    ):
        obj = await db.get(model, item_id)
        if obj is None:
            raise NotFoundError(f"{model.__name__} {item_id} not found")
        return read_schema.model_validate(obj)

    @router.put(
        "/{item_id}",
        response_model=read_schema,
        summary=f"Update a {model.__name__}",
    )
    async def _update(
        item_id: str,
        body: update_schema,
        db: AsyncSession = Depends(get_db),
        _admin: object = Depends(current_admin),
    ):
        obj = await db.get(model, item_id)
        if obj is None:
            raise NotFoundError(f"{model.__name__} {item_id} not found")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(obj, k, v)
        await db.commit()
        await db.refresh(obj)
        return read_schema.model_validate(obj)

    if hasattr(model, "__tablename__") and model.__tablename__ in (
        "products",
        "services",
        "inventory_items",
    ):
        @router.delete(
            "/{item_id}",
            response_model=Message,
            summary=f"Delete a {model.__name__}",
        )
        async def _delete(
            item_id: str,
            db: AsyncSession = Depends(get_db),
            _admin: object = Depends(current_admin),
        ):
            obj = await db.get(model, item_id)
            if obj is None:
                raise NotFoundError(f"{model.__name__} {item_id} not found")
            await db.delete(obj)
            await db.commit()
            return Message(message=f"{model.__name__} {item_id} deleted")


# ---- Products ----
products_router = APIRouter(prefix="/product", tags=["admin:products"])
_make_crud_routes(
    products_router, Product,
    ProductCreate, ProductUpdate, ProductRead,
    "product",
)


# ---- Services ----
services_router = APIRouter(prefix="/service", tags=["admin:services"])
_make_crud_routes(
    services_router, Service,
    ServiceCreate, ServiceUpdate, ServiceRead,
    "service",
)


# ---- Inventory Categories ----
inventory_cat_router = APIRouter(
    prefix="/inventory/category", tags=["admin:inventory"]
)


@inventory_cat_router.post(
    "",
    response_model=InventoryCategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an inventory category",
)
async def create_category(
    body: InventoryCategoryCreate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    cat = InventoryCategory(**body.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return InventoryCategoryRead.model_validate(cat)


@inventory_cat_router.get(
    "",
    response_model=list[InventoryCategoryRead],
    summary="List inventory categories",
)
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    # Exclude synthetic categories created during the DDB→PG migration
    stmt = (
        select(InventoryCategory)
        .where(InventoryCategory.name.not_like('%synthetic%'))
        .order_by(InventoryCategory.name)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [InventoryCategoryRead.model_validate(r) for r in rows]


@inventory_cat_router.get(
    "/{category_id}",
    response_model=InventoryCategoryRead,
    summary="Get an inventory category",
)
async def get_category(
    category_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    cat = await db.get(InventoryCategory, category_id)
    if cat is None:
        raise NotFoundError(f"InventoryCategory {category_id} not found")
    # Block access to synthetic categories
    if cat.name and 'synthetic' in cat.name.lower():
        raise NotFoundError(f"InventoryCategory {category_id} not found")
    return InventoryCategoryRead.model_validate(cat)


# ---- Inventory Items ----
inventory_items_router = APIRouter(
    prefix="/inventory/category/{category_id}/item", tags=["admin:inventory"]
)


@inventory_items_router.post(
    "",
    response_model=InventoryItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an inventory item in a category",
)
async def create_item(
    category_id: str,
    body: InventoryItemCreate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    # Verify the category exists
    cat = await db.get(InventoryCategory, category_id)
    if cat is None:
        raise NotFoundError(f"InventoryCategory {category_id} not found")
    item = InventoryItem(category_id=category_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return InventoryItemRead.model_validate(item)


@inventory_items_router.get(
    "",
    response_model=list[InventoryItemRead],
    summary="List items in a category",
)
async def list_items(
    category_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    stmt = (
        select(InventoryItem)
        .where(InventoryItem.category_id == category_id)
        .order_by(InventoryItem.name)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [InventoryItemRead.model_validate(r) for r in rows]


@inventory_items_router.get(
    "/{item_id}",
    response_model=InventoryItemRead,
    summary="Get an inventory item",
)
async def get_item(
    category_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    item = await db.get(InventoryItem, item_id)
    if item is None or item.category_id != category_id:
        raise NotFoundError(f"InventoryItem {item_id} not found in category {category_id}")
    return InventoryItemRead.model_validate(item)


@inventory_items_router.put(
    "/{item_id}",
    response_model=InventoryItemRead,
    summary="Update an inventory item",
)
async def update_item(
    category_id: str,
    item_id: str,
    body: InventoryItemUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    item = await db.get(InventoryItem, item_id)
    if item is None or item.category_id != category_id:
        raise NotFoundError(f"InventoryItem {item_id} not found in category {category_id}")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    await db.commit()
    await db.refresh(item)
    return InventoryItemRead.model_validate(item)


# Also expose /inventory/items (list all) at the admin level
inventory_all_router = APIRouter(prefix="/inventory", tags=["admin:inventory"])


@inventory_all_router.get(
    "/items",
    response_model=list[InventoryItemRead],
    summary="List ALL inventory items (admin)",
)
async def list_all_items(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    _admin: object = Depends(current_admin),
):
    from app.core.pagination import paginate, set_pagination_headers
    stmt = select(InventoryItem).order_by(InventoryItem.created_at.desc())
    items, total = await paginate(db, stmt, limit, offset)
    if response is not None:
        set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [InventoryItemRead.model_validate(r) for r in items]
