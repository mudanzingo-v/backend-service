"""
Pydantic v2 schemas for request/response models — re-exports.

Naming convention:
- `*Create` — body for POST endpoints
- `*Update` — body for PUT endpoints
- `*Read` — response shape
- `*InDB` — internal representation (rarely used; models are usually returned directly)

Schemas are split into per-domain files (quotation.py, auction.py, catalog.py,
provider.py, saler.py, payment.py, stats.py, common.py) for maintainability.
This `__init__.py` re-exports everything so existing imports
(`from app.schemas import QuotationRead`) keep working.
"""
from __future__ import annotations

# Auction + Preference
from app.schemas.auction import (
    AuctionAdminAssign,
    AuctionCreate,
    AuctionItemObject,
    AuctionProviderUpdate,
    AuctionRead,
    AuctionSelectBody,
    AuctionUpdate,
    PreferenceRead,
)

# Catalog
from app.schemas.catalog import (
    InventoryCategoryCreate,
    InventoryCategoryRead,
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    ServiceCreate,
    ServiceRead,
    ServiceUpdate,
)

# Common
from app.schemas.common import Message

# Payment + Location
from app.schemas.payment import (
    LocationRead,
    PaymentCreateDeposit,
    PaymentCreateMP,
    PaymentRead,
)

# Provider + Truck
from app.schemas.provider import (
    ProviderRead,
    ProviderUpdate,
    TruckCreate,
    TruckRead,
    TruckUpdate,
)

# Quotation
from app.schemas.quotation import (
    QuotationCreateAdmin,
    QuotationCreateB2C,
    QuotationRead,
    QuotationUpdate,
)

# Saler
from app.schemas.saler import SalerCreate, SalerRead, SalerUpdate

# Stats
from app.schemas.stats import Stats

__all__ = [
    "Message",
    # Quotation
    "QuotationCreateB2C", "QuotationCreateAdmin", "QuotationUpdate", "QuotationRead",
    # Auction
    "AuctionItemObject", "AuctionCreate", "AuctionUpdate", "AuctionSelectBody",
    "AuctionAdminAssign", "AuctionProviderUpdate", "AuctionRead",
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
