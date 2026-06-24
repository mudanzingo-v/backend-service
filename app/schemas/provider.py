"""Provider + Truck schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str | None = None
    name: str | None = None
    phone: str | None = None
    rfc: str | None = None
    address: str | None = None
    active: bool


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    phone: str | None = None
    rfc: str | None = None
    address: str | None = None
    active: bool | None = None


class TruckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    plates: str | None = None
    capacity_kg: Decimal | None = None
    capacity_m3: Decimal | None = None
    active: bool = True


class TruckUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    plates: str | None = None
    capacity_kg: Decimal | None = None
    capacity_m3: Decimal | None = None
    active: bool | None = None


class TruckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    provider_id: str
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    plates: str | None = None
    capacity_kg: Decimal | None = None
    capacity_m3: Decimal | None = None
    active: bool
    created_at: datetime
    updated_at: datetime
