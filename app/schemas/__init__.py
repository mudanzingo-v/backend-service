"""
Pydantic v2 schemas for request/response models.

Naming convention:
- `*Create` — body for POST endpoints
- `*Update` — body for PUT endpoints
- `*Read` — response shape
- `*InDB` — internal representation (rarely used; models are usually returned directly)
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---- Common ----
class Message(BaseModel):
    message: str


# =============================================================================
# Quotation
# =============================================================================
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
    channel_sales: Optional[str] = None
    state: Optional[str] = None
    service_name: Optional[str] = None
    service_type: Optional[str] = None
    service_zone: Optional[str] = None
    service_hour: Optional[str] = None
    service_date: Optional[str] = None
    service_internal: Optional[str] = None
    id_saler: Optional[str] = None
    saler: Optional[dict[str, Any]] = None

    origin_postal_code: Optional[str] = None
    origin_adress: Optional[str] = None
    origin_type: Optional[str] = None
    origin_transport_type: Optional[str] = None
    origin_pulley: Optional[str] = None
    origin_restrictions: Optional[str] = None
    origin_floor: Optional[str] = None

    destination_postal_code: Optional[str] = None
    destination_adress: Optional[str] = None
    destination_type: Optional[str] = None
    destination_transport_type: Optional[str] = None
    destination_pulley: Optional[str] = None
    destination_restrictions: Optional[str] = None
    destination_floor: Optional[str] = None

    services: Optional[list[Any]] = None
    products: Optional[list[Any]] = None
    items: Optional[list[Any]] = None


class QuotationUpdate(BaseModel):
    """PUT /quotation/{id} — partial update (admin)."""

    model_config = ConfigDict(extra="forbid")

    # Client
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    # Service
    state: Optional[str] = None
    service_name: Optional[str] = None
    service_type: Optional[str] = None
    service_zone: Optional[str] = None
    service_hour: Optional[str] = None
    service_date: Optional[str] = None
    service_internal: Optional[str] = None
    # Sales
    id_saler: Optional[str] = None
    channel_sales: Optional[str] = None
    # Origin
    origin_postal_code: Optional[str] = None
    origin_adress: Optional[str] = None
    origin_type: Optional[str] = None
    origin_transport_type: Optional[str] = None
    origin_pulley: Optional[str] = None
    origin_restrictions: Optional[str] = None
    origin_floor: Optional[str] = None
    # Destination
    destination_postal_code: Optional[str] = None
    destination_adress: Optional[str] = None
    destination_type: Optional[str] = None
    destination_transport_type: Optional[str] = None
    destination_pulley: Optional[str] = None
    destination_restrictions: Optional[str] = None
    destination_floor: Optional[str] = None
    services: Optional[list[Any]] = None
    products: Optional[list[Any]] = None
    items: Optional[list[Any]] = None


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
    state: Optional[str] = None
    service_name: Optional[str] = None
    service_type: Optional[str] = None
    service_zone: Optional[str] = None
    service_hour: Optional[str] = None
    service_date: Optional[str] = None
    service_internal: Optional[str] = None
    id_saler: Optional[str] = None
    saler: Optional[dict[str, Any]] = None
    channel_sales: Optional[str] = None

    origin_postal_code: Optional[str] = None
    origin_adress: Optional[str] = None
    origin_type: Optional[str] = None
    origin_transport_type: Optional[str] = None
    origin_pulley: Optional[str] = None
    origin_restrictions: Optional[str] = None
    origin_floor: Optional[str] = None

    destination_postal_code: Optional[str] = None
    destination_adress: Optional[str] = None
    destination_type: Optional[str] = None
    destination_transport_type: Optional[str] = None
    destination_pulley: Optional[str] = None
    destination_restrictions: Optional[str] = None
    destination_floor: Optional[str] = None

    services: Optional[list[Any]] = None
    products: Optional[list[Any]] = None
    items: Optional[list[Any]] = None

    # Wizard progress (B2C public form). NULL wizard_step + wizard_complete=False
    # means "admin-created, not from the wizard". NULL wizard_step + wizard_complete=True
    # means "wizard finished (now waiting for admin to publish)".
    wizard_step: Optional[int] = None
    wizard_complete: bool = False

    created_at: datetime
    updated_at: datetime


# =============================================================================
# Auction
# =============================================================================
class AuctionItemObject(BaseModel):
    """Original Lambda shape: { id: str, offer: str }."""

    model_config = ConfigDict(extra="forbid")

    id: str
    offer: str


class AuctionCreate(BaseModel):
    """Provider submits an offer (POST /quotation/{id}/auction)."""

    model_config = ConfigDict(extra="forbid")

    services: Optional[list[AuctionItemObject]] = None
    products: Optional[list[AuctionItemObject]] = None
    price_load: str = Field(..., description="Total price of the load (as string, like the original)")
    people: str
    id_truck: str
    cash_on_delivery: Optional[str] = None  # "true" or "false" (matches the original)


class AuctionAdminAssign(BaseModel):
    """Admin assigns a provider to a quotation (with a suggested price).

    Creates a new Auction with state=PENDING and the admin's price as
    the initial bid. The provider can then accept as-is, counter-offer,
    or decline.
    """

    model_config = ConfigDict(extra="forbid")

    admin_budget: Decimal = Field(..., description="Admin's suggested price (MXN)")
    people: Optional[str] = None
    id_truck: Optional[str] = None
    note: Optional[str] = None  # Optional admin note for the provider


class AuctionProviderUpdate(BaseModel):
    """Provider accepts / counters an admin-assigned auction.

    The provider can either:
    - Accept as-is (no body required, or just provider_note)
    - Counter-offer (provide price_load, people, etc.)
    """

    model_config = ConfigDict(extra="forbid")

    price_load: Optional[str] = None  # If set, recalculates subtotal/fees/total
    people: Optional[str] = None
    id_truck: Optional[str] = None
    provider_note: Optional[str] = None
    # If true, the provider is confirming the admin's price (no changes)
    accept_admin_price: bool = False


class AuctionUpdate(BaseModel):
    """Admin updates an existing auction (PUT)."""

    model_config = ConfigDict(extra="forbid")

    services: Optional[list[AuctionItemObject]] = None
    products: Optional[list[AuctionItemObject]] = None
    price_load: Optional[str] = None
    people: Optional[str] = None
    id_truck: Optional[str] = None
    state: Optional[str] = None
    admin_budget: Optional[Decimal] = None
    provider_note: Optional[str] = None


class AuctionSelectBody(BaseModel):
    """B2C client selects an auction (PUT /quotation/{id}/auction)."""

    model_config = ConfigDict(extra="forbid")

    id_auction: str
    cash_on_delivery: str = Field(..., description='"true" or "false"')


class AuctionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    quotation_id: str
    provider_id: str
    price_load: Decimal
    subtotal: Decimal
    mobbit_fee: Decimal
    iva: Decimal
    transaction_fee: Decimal
    total: Decimal
    cash_on_delivery_provider: Optional[Decimal] = None
    cash_on_delivery_mobbit: Optional[Decimal] = None
    people: Optional[str] = None
    id_truck: Optional[str] = None
    state: str
    services: Optional[list[Any]] = None
    products: Optional[list[Any]] = None
    admin_budget: Optional[Decimal] = None
    provider_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Preference (MercadoPago)
# =============================================================================
class PreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    auction_id: str
    mp_id: Optional[str] = None
    init_point: Optional[str] = None
    sandbox_init_point: Optional[str] = None
    date_created: Optional[str] = None
    client_id: Optional[str] = None
    collector_id: Optional[str] = None
    operation_type: Optional[str] = None
    items: Optional[str] = None
    payer: Optional[str] = None
    shipment: Optional[str] = None
    created_at: datetime


# =============================================================================
# Catalog
# =============================================================================
class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[Decimal] = None
    url_image: Optional[str] = None
    category_id: Optional[str] = None
    active: bool = True


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    description: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[Decimal] = None
    url_image: Optional[str] = None
    category_id: Optional[str] = None
    active: Optional[bool] = None


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[Decimal] = None
    url_image: Optional[str] = None
    category_id: Optional[str] = None
    active: bool
    created_at: datetime
    updated_at: datetime


class ServiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    price: Optional[Decimal] = None
    active: bool = True


class ServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    active: Optional[bool] = None


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: Optional[str] = None
    price: Optional[Decimal] = None
    active: bool
    created_at: datetime
    updated_at: datetime


class InventoryCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    active: bool = True


class InventoryCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: Optional[str] = None
    active: bool
    created_at: datetime
    updated_at: datetime


class InventoryItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    url_image: Optional[str] = None
    length: Optional[Decimal] = None
    width: Optional[Decimal] = None
    height: Optional[Decimal] = None
    weight: Optional[Decimal] = None
    active: bool = True


class InventoryItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    url_image: Optional[str] = None
    length: Optional[Decimal] = None
    width: Optional[Decimal] = None
    height: Optional[Decimal] = None
    weight: Optional[Decimal] = None
    active: Optional[bool] = None


class InventoryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    url_image: Optional[str] = None
    length: Optional[Decimal] = None
    width: Optional[Decimal] = None
    height: Optional[Decimal] = None
    weight: Optional[Decimal] = None
    category_id: str
    active: bool
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Provider / Truck
# =============================================================================
class ProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    rfc: Optional[str] = None
    address: Optional[str] = None
    active: bool


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    phone: Optional[str] = None
    rfc: Optional[str] = None
    address: Optional[str] = None
    active: Optional[bool] = None


class TruckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    plates: Optional[str] = None
    capacity_kg: Optional[Decimal] = None
    capacity_m3: Optional[Decimal] = None
    active: bool = True


class TruckUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    plates: Optional[str] = None
    capacity_kg: Optional[Decimal] = None
    capacity_m3: Optional[Decimal] = None
    active: Optional[bool] = None


class TruckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    provider_id: str
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    plates: Optional[str] = None
    capacity_kg: Optional[Decimal] = None
    capacity_m3: Optional[Decimal] = None
    active: bool
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Saler
# =============================================================================
class SalerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    commission_pct: Optional[Decimal] = None
    active: bool = True


class SalerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    commission_pct: Optional[Decimal] = None
    active: Optional[bool] = None


class SalerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    commission_pct: Optional[Decimal] = None
    active: bool
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Payment
# =============================================================================
class PaymentCreateMP(BaseModel):
    """Admin creates an MP payment preference for a quotation."""

    model_config = ConfigDict(extra="forbid")
    id_auction: str


class PaymentCreateDeposit(BaseModel):
    """Admin records a deposit payment."""

    model_config = ConfigDict(extra="forbid")
    id_auction: str
    amount: Decimal
    reference: Optional[str] = None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    quotation_id: str
    auction_id: Optional[str] = None
    type: str
    state: str
    amount: Optional[Decimal] = None
    currency: str
    mp_payment_id: Optional[str] = None
    mp_preference_id: Optional[str] = None
    mp_status: Optional[str] = None
    mp_status_detail: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Location
# =============================================================================
class LocationRead(BaseModel):
    """Mirrors the Copomex response (passthrough)."""

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Stats
# =============================================================================
class Stats(BaseModel):
    """Aggregate counts for the admin dashboard. Single query, single round trip."""

    quotations: int = 0
    auctions: int = 0
    products: int = 0
    services: int = 0
    inventory_items: int = 0
    inventory_categories: int = 0
    providers: int = 0
    salers: int = 0
    payments: int = 0
    trucks: int = 0


__all__ = [
    "Message",
    # Quotation
    "QuotationCreateB2C", "QuotationCreateAdmin", "QuotationUpdate", "QuotationRead",
    # Auction
    "AuctionItemObject", "AuctionCreate", "AuctionUpdate", "AuctionSelectBody", "AuctionRead",
    # Preference
    "PreferenceRead",
    # Catalog
    "ProductCreate", "ProductUpdate", "ProductRead",
    "ServiceCreate", "ServiceUpdate", "ServiceRead",
    "InventoryCategoryCreate", "InventoryCategoryRead",
    "InventoryItemCreate", "InventoryItemUpdate", "InventoryItemRead",
    # Provider / Truck
    "ProviderRead", "ProviderUpdate",
    "TruckCreate", "TruckUpdate", "TruckRead",
    # Saler
    "SalerCreate", "SalerUpdate", "SalerRead",
    # Payment
    "PaymentCreateMP", "PaymentCreateDeposit", "PaymentRead",
    # Location
    "LocationRead",
    # Stats
    "Stats",
]
