"""
SQLAlchemy ORM models.

These translate the single-table DynamoDB design (see
`docs/research/business-domain.md` §3) into a relational schema.
The business logic stays the same; only the storage layer changes.

Key design choices:
- `id` is always a UUID4 string (was a partition key suffix in DynamoDB).
- Money is stored as `Numeric(12,2)` (was a stringified float in DDB).
- Timestamps use `TIMESTAMPTZ` (was an untyped string in DDB).
- The "auction" identity is still (quotation_id, provider_id), modelled
  as a composite unique constraint (matches the original `(pk, sk)` design).
- `services`, `products`, `items` fields are `JSONB` (was a `List` of `M`
  in DDB). We keep them flexible for the MVP.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# =============================================================================
# Quotation
# =============================================================================
class Quotation(Base):
    """
    A quotation created by a client (B2C, public) or an admin (RCCM).

    Single-table equivalent: `pk = QUOTATION#<id>`, `sk = METADATA`.
    """

    __tablename__ = "quotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Required
    client_name: Mapped[str] = mapped_column(String(255))
    client_phone: Mapped[str] = mapped_column(String(64))
    client_email: Mapped[str] = mapped_column(String(255))

    # Optional (admin can fill these in)
    channel_sales: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    service_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_hour: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_internal: Mapped[str | None] = mapped_column(String(64), nullable=True)
    id_saler: Mapped[str | None] = mapped_column(String(36), nullable=True)
    saler: Mapped[str | None] = mapped_column(JSONB, nullable=True)

    # Addresses
    origin_postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    origin_adress: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_transport_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_pulley: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_floor: Mapped[str | None] = mapped_column(String(16), nullable=True)

    destination_postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    destination_adress: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_transport_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_pulley: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_floor: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Lists (JSON arrays of ids/objects)
    services: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    products: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    items: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Wizard progress (B2C public form). Separate from `state` so the lifecycle
    # state can be analysed independently of which step the user is on.
    # NULL wizard_step means "not from the wizard" (admin-created) OR "wizard finished".
    # Use `wizard_complete` to distinguish.
    wizard_step: Mapped[int | None] = mapped_column(nullable=True, index=True)
    wizard_complete: Mapped[bool] = mapped_column(default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    auctions: Mapped[list["Auction"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Quotation {self.id} state={self.state}>"


# =============================================================================
# Auction (provider's bid on a quotation)
# =============================================================================
class Auction(Base):
    """
    A provider's offer for a quotation.

    Single-table equivalent: `pk = QUOTATION#<q_id>`, `sk = AUCTION#<provider_id>`.
    Identity is the pair (quotation_id, provider_id) — same as the original
    Rust lambda. See `docs/research/business-domain.md` §3.2.
    """

    __tablename__ = "auctions"
    __table_args__ = (
        UniqueConstraint("quotation_id", "provider_id", name="uq_auction_quotation_provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    quotation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quotations.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[str] = mapped_column(String(128), index=True)  # Cognito `sub`

    # Pricing (see `pricing_service.py` for calculation)
    price_load: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    mobbit_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    iva: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    transaction_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    # Cash on delivery split (15% / 85% by default — see pricing env)
    cash_on_delivery_provider: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    cash_on_delivery_mobbit: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # Logistics
    people: Mapped[str | None] = mapped_column(String(64), nullable=True)
    id_truck: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Selection state
    state: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    # PENDING | SELECTED | REJECTED | ACCEPTED | PAID | DECLINED

    # Admin's suggested price (set when admin assigns the provider). The
    # provider can then accept as-is, counter-offer (overwrite price fields),
    # or decline. Nullable because older auctions were created directly
    # by the provider without an admin budget.
    admin_budget: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # Provider's note (optional message when accepting / countering / declining)
    provider_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Services and products (lists of {id, offer} in the original — kept as JSONB)
    services: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    products: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    quotation: Mapped["Quotation"] = relationship(back_populates="auctions")
    preferences: Mapped[list["Preference"]] = relationship(
        back_populates="auction", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Auction {self.id} q={self.quotation_id} p={self.provider_id} state={self.state}>"


# =============================================================================
# Preference (MercadoPago payment preference)
# =============================================================================
class Preference(Base):
    """
    A MercadoPago checkout preference created when the client selects an auction.

    Single-table equivalent: `pk = AUCTION#<provider_id>`, `sk = PREFERENCE`.
    """

    __tablename__ = "preferences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    auction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("auctions.id", ondelete="CASCADE"), index=True
    )

    # MP response fields
    mp_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    init_point: Mapped[str | None] = mapped_column(Text, nullable=True)
    sandbox_init_point: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_created: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    items: Mapped[str | None] = mapped_column(Text, nullable=True)
    payer: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    auction: Mapped["Auction"] = relationship(back_populates="preferences")

    def __repr__(self) -> str:
        return f"<Preference {self.id} mp_id={self.mp_id}>"


# =============================================================================
# Catalog: Product
# =============================================================================
class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    url_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


# =============================================================================
# Catalog: Service
# =============================================================================
class Service(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


# =============================================================================
# Catalog: Inventory Category
# =============================================================================
class InventoryCategory(Base):
    __tablename__ = "inventory_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


# =============================================================================
# Catalog: Inventory Item
# =============================================================================
class InventoryItem(Base):
    """
    Note: original DDB schema had typos `lenght` and `weigh`. We fix them
    here to `length` and `weight`. The single-table equivalent was
    `pk = INVENTORY#CATEGORY#<id_category>`, `sk = ITEM#<uuid>`.
    """

    __tablename__ = "inventory_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    url_image: Mapped[str | None] = mapped_column(Text, nullable=True)

    length: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    width: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    height: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_categories.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


# =============================================================================
# Provider
# =============================================================================
class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # Cognito sub
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rfc: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    trucks: Mapped[list["Truck"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Provider {self.id} name={self.name}>"


# =============================================================================
# Truck (provider's vehicle)
# =============================================================================
class Truck(Base):
    __tablename__ = "trucks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )

    brand: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    year: Mapped[int | None] = mapped_column(nullable=True)
    plates: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    capacity_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    capacity_m3: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    provider: Mapped["Provider"] = relationship(back_populates="trucks")


# =============================================================================
# Saler (sales rep)
# =============================================================================
class Saler(Base):
    __tablename__ = "salers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commission_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


# =============================================================================
# Payment
# =============================================================================
class Payment(Base):
    """
    Tracks payments. In the MVP, the MP webhook is stubbed (see
    `docs/research/business-domain.md` §6.1) so most fields stay null
    until the webhook is implemented.
    """

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quotation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quotations.id", ondelete="CASCADE"), index=True
    )
    auction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("auctions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    type: Mapped[str] = mapped_column(String(32), index=True)
    # MERCADOPAGO | DEPOSIT
    state: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    # PENDING | APPROVED | REJECTED | REFUNDED

    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="MXN")

    # MP-specific
    mp_payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    mp_preference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mp_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mp_status_detail: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Payment {self.id} type={self.type} state={self.state}>"


__all__ = [
    "Quotation",
    "Auction",
    "Preference",
    "Product",
    "Service",
    "InventoryCategory",
    "InventoryItem",
    "Provider",
    "Truck",
    "Saler",
    "Payment",
]
