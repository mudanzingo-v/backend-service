"""Quotation schemas — request/response models for the quotation domain."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class QuotationCreateB2C(BaseModel):
    """B2C public lead — only contact info (matches the original Lambda)."""

    model_config = ConfigDict(extra="forbid")

    client_name: str = Field(..., min_length=1, max_length=255)
    client_phone: str = Field(..., min_length=1, max_length=64)
    client_email: EmailStr


class QuotationCreateAdmin(BaseModel):
    """Admin creates a fully-detailed quotation on behalf of a client."""

    model_config = ConfigDict(extra="forbid")

    # Required
    client_name: str = Field(..., min_length=1, max_length=255)
    client_phone: str = Field(..., min_length=1, max_length=64)
    client_email: EmailStr

    # Optional
    channel_sales: str | None = None
    state: str | None = None
    service_name: str | None = None
    service_type: str | None = None
    service_zone: str | None = None
    service_hour: str | None = None
    service_date: str | None = None
    service_internal: str | None = None
    id_saler: str | None = None
    saler: dict[str, Any] | None = None

    origin_postal_code: str | None = None
    origin_adress: str | None = None
    origin_type: str | None = None
    origin_transport_type: str | None = None
    origin_pulley: str | None = None
    origin_restrictions: str | None = None
    origin_floor: str | None = None

    destination_postal_code: str | None = None
    destination_adress: str | None = None
    destination_type: str | None = None
    destination_transport_type: str | None = None
    destination_pulley: str | None = None
    destination_restrictions: str | None = None
    destination_floor: str | None = None

    services: list[Any] | None = None
    products: list[Any] | None = None
    items: list[Any] | None = None


class QuotationUpdate(BaseModel):
    """PUT /quotation/{id} — partial update (admin)."""

    model_config = ConfigDict(extra="forbid")

    # Client
    client_name: str | None = None
    client_phone: str | None = None
    client_email: EmailStr | None = None
    # Service
    state: str | None = None
    service_name: str | None = None
    service_type: str | None = None
    service_zone: str | None = None
    service_hour: str | None = None
    service_date: str | None = None
    service_internal: str | None = None
    # Sales
    id_saler: str | None = None
    channel_sales: str | None = None
    # Origin
    origin_postal_code: str | None = None
    origin_adress: str | None = None
    origin_type: str | None = None
    origin_transport_type: str | None = None
    origin_pulley: str | None = None
    origin_restrictions: str | None = None
    origin_floor: str | None = None
    # Destination
    destination_postal_code: str | None = None
    destination_adress: str | None = None
    destination_type: str | None = None
    destination_transport_type: str | None = None
    destination_pulley: str | None = None
    destination_restrictions: str | None = None
    destination_floor: str | None = None
    services: list[Any] | None = None
    products: list[Any] | None = None
    items: list[Any] | None = None
    # Wizard progress (B2C public form). Mirror of QuotationRead §"Wizard
    # progress" — the wizard (`web-portal/app/[locale]/cotizar/actions.ts`
    # `updateStep*Action`) PUTs these on every step transition via the
    # `lib/api/b2cAdapter.ts::toBackendWizardState()` mapping. The DB model
    # (`app/models/__init__.py:103-104`) already declares these columns,
    # the service layer (`app/services/quotation.py:96-105`) sets
    # attributes by name from `body.model_dump(exclude_unset=True)`, so
    # declaring them here is the only change needed to make the wizard's
    # PUTs succeed against the `extra="forbid"` Pydantic config. Closes
    # verify-report-T4.md §B-1 (BLOCKER).
    wizard_step: int | None = None
    wizard_complete: bool = False


class QuotationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_name: str
    client_phone: str
    client_email: str

    # Lifecycle state. Valid values (enforced at the service layer, not the DB):
    #   DRAFT       — being created (admin or wizard in progress)
    #   QUOTED      — published, visible to providers
    #   BIDDING     — has at least one auction
    #   AWARDED     — client selected an auction
    #   IN_PROGRESS — provider accepted
    #   COMPLETED   — service delivered
    #   CANCELLED | REJECTED | FAILED — terminal
    state: str | None = None
    service_name: str | None = None
    service_type: str | None = None
    service_zone: str | None = None
    service_hour: str | None = None
    service_date: str | None = None
    service_internal: str | None = None
    id_saler: str | None = None
    saler: dict[str, Any] | None = None
    channel_sales: str | None = None

    origin_postal_code: str | None = None
    origin_adress: str | None = None
    origin_type: str | None = None
    origin_transport_type: str | None = None
    origin_pulley: str | None = None
    origin_restrictions: str | None = None
    origin_floor: str | None = None

    destination_postal_code: str | None = None
    destination_adress: str | None = None
    destination_type: str | None = None
    destination_transport_type: str | None = None
    destination_pulley: str | None = None
    destination_restrictions: str | None = None
    destination_floor: str | None = None

    services: list[Any] | None = None
    products: list[Any] | None = None
    items: list[Any] | None = None

    # Wizard progress (B2C public form). NULL wizard_step + wizard_complete=False
    # means "admin-created, not from the wizard". NULL wizard_step + wizard_complete=True
    # means "wizard finished (now waiting for admin to publish)".
    wizard_step: int | None = None
    wizard_complete: bool = False

    created_at: datetime
    updated_at: datetime
