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
    __tablename__ = "quotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_name: Mapped[str] = mapped_column(String(255))
    client_phone: Mapped[str] = mapped_column(String(64))
    client_email: Mapped[str] = mapped_column(String(255))
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
    services: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    products: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    wizard_step: Mapped[int | None] = mapped_column(nullable=True, index=True)
    wizard_complete: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )
    auctions: Mapped[list[Auction]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Quotation {self.id} state={self.state}>"


# =============================================================================
# Auction
# =============================================================================
class Auction(Base):
    __tablename__ = "auctions"
    __table_args__ = (
        UniqueConstraint("quotation_id", "provider_id", name="uq_auction_quotation_provider"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quotation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quotations.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[str] = mapped_column(String(128), index=True)
    price_load: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    mobbit_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    iva: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    transaction_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    cash_on_delivery_provider: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cash_on_delivery_mobbit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    people: Mapped[str | None] = mapped_column(String(64), nullable=True)
    id_truck: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    admin_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    provider_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    services: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    products: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )
    quotation: Mapped[Quotation] = relationship(back_populates="auctions")
    checkout_sessions: Mapped[list[CheckoutSession]] = relationship(
        back_populates="auction", cascade="all, delete-orphan"
    )


# =============================================================================
# CheckoutSession
# =============================================================================
class CheckoutSession(Base):
    __tablename__ = "checkout_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    auction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("auctions.id", ondelete="CASCADE"), index=True
    )
    stripe_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount_total: Mapped[int | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="mxn")
    last_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    auction: Mapped[Auction] = relationship(back_populates="checkout_sessions")


# =============================================================================
# Product, Service, InventoryCategory, InventoryItem
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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class InventoryCategory(Base):
    __tablename__ = "inventory_categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class InventoryItem(Base):
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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


# =============================================================================
# Provider, Truck
# =============================================================================
class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True, unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rfc: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    verification_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    kyc_status: Mapped[str] = mapped_column(String(32), default="NOT_STARTED", nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)
    trucks: Mapped[list[Truck]] = relationship(back_populates="provider", cascade="all, delete-orphan")


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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)
    provider: Mapped[Provider] = relationship(back_populates="trucks")


# =============================================================================
# Saler
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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


# =============================================================================
# Invoice (CFDI 4.0)
# =============================================================================
class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    payment_id: Mapped[str] = mapped_column(String(36), ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    quotation_id: Mapped[str] = mapped_column(String(36), ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    rfc_emisor: Mapped[str] = mapped_column(String(13), nullable=False)
    rfc_receptor: Mapped[str] = mapped_column(String(13), nullable=False)
    cfdi_use: Mapped[str] = mapped_column(String(8), default="G03", nullable=False)
    payment_method: Mapped[str] = mapped_column(String(8), default="PPD", nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    iva: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    cfdi_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    xml_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    stamped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


# =============================================================================
# Payment
# =============================================================================
class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quotation_id: Mapped[str] = mapped_column(String(36), ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    auction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("auctions.id", ondelete="SET NULL"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="MXN")
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stripe_payment_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


# =============================================================================
# ProviderDocument (KYC)
# =============================================================================
class ProviderDocument(Base):
    __tablename__ = "provider_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider_id: Mapped[str] = mapped_column(String(128), ForeignKey("providers.id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


# =============================================================================
# AuditLog
# =============================================================================
class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor_pool: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False, index=True)


# =============================================================================
# Rating (provider review)
# =============================================================================
class Rating(Base):
    """A B2C client's rating of a provider after service completion."""

    __tablename__ = "ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    auction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("auctions.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    quotation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quotations.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[int] = mapped_column(nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

# =============================================================================
class ProviderAvailability(Base):
    """Provider availability for a specific date."""

    __tablename__ = "provider_availability"
    __table_args__ = (
        UniqueConstraint("provider_id", "date", name="uq_provider_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Time slots as JSON array: ["09:00", "10:00", "11:00", ...]
    slots: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


__all__ = [
    "AuditLog",
    "Auction",
    "ProviderAvailability",
    "Rating",
    "CheckoutSession",
    "InventoryCategory",
    "InventoryItem",
    "Invoice",
    "Payment",
    "Product",
    "Provider",
    "ProviderDocument",
    "Quotation",
    "Saler",
    "Service",
    "Truck",
]
