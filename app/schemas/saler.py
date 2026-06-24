"""Saler schemas — sales representative CRUD."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SalerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    commission_pct: Decimal | None = None
    active: bool = True


class SalerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    commission_pct: Decimal | None = None
    active: bool | None = None


class SalerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    commission_pct: Decimal | None = None
    active: bool
    created_at: datetime
    updated_at: datetime
