"""Catalog schemas — products, services, inventory categories, inventory items."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ---- Product ----
class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    sku: str | None = None
    price: Decimal | None = None
    url_image: str | None = None
    category_id: str | None = None
    active: bool = True


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    sku: str | None = None
    price: Decimal | None = None
    url_image: str | None = None
    category_id: str | None = None
    active: bool | None = None


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None = None
    sku: str | None = None
    price: Decimal | None = None
    url_image: str | None = None
    category_id: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


# ---- Service ----
class ServiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = None
    active: bool = True


class ServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    active: bool | None = None


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None = None
    price: Decimal | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


# ---- Inventory Category ----
class InventoryCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    active: bool = True


class InventoryCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


# ---- Inventory Item ----
class InventoryItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    url_image: str | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    weight: Decimal | None = None
    active: bool = True


class InventoryItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    url_image: str | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    weight: Decimal | None = None
    active: bool | None = None


class InventoryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    url_image: str | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    weight: Decimal | None = None
    category_id: str
    active: bool
    created_at: datetime
    updated_at: datetime
