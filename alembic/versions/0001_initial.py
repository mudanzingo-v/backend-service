"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-16

Creates the full schema for Mobbit Backend Service.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Quotations ---
    op.create_table(
        "quotations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_name", sa.String(255), nullable=False),
        sa.Column("client_phone", sa.String(64), nullable=False),
        sa.Column("client_email", sa.String(255), nullable=False),
        sa.Column("channel_sales", sa.String(64)),
        sa.Column("state", sa.String(64), index=True),
        sa.Column("service_name", sa.String(255)),
        sa.Column("service_type", sa.String(64)),
        sa.Column("service_zone", sa.String(64)),
        sa.Column("service_hour", sa.String(64)),
        sa.Column("service_date", sa.String(64)),
        sa.Column("service_internal", sa.String(64)),
        sa.Column("id_saler", sa.String(36)),
        sa.Column("saler", postgresql.JSONB),
        sa.Column("origin_postal_code", sa.String(16)),
        sa.Column("origin_adress", sa.Text),
        sa.Column("origin_type", sa.String(64)),
        sa.Column("origin_transport_type", sa.String(64)),
        sa.Column("origin_pulley", sa.String(64)),
        sa.Column("origin_restrictions", sa.Text),
        sa.Column("origin_floor", sa.String(16)),
        sa.Column("destination_postal_code", sa.String(16)),
        sa.Column("destination_adress", sa.Text),
        sa.Column("destination_type", sa.String(64)),
        sa.Column("destination_transport_type", sa.String(64)),
        sa.Column("destination_pulley", sa.String(64)),
        sa.Column("destination_restrictions", sa.Text),
        sa.Column("destination_floor", sa.String(16)),
        sa.Column("services", postgresql.JSONB),
        sa.Column("products", postgresql.JSONB),
        sa.Column("items", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- Inventory Categories ---
    op.create_table(
        "inventory_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- Products ---
    op.create_table(
        "products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("sku", sa.String(64), index=True),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("url_image", sa.Text),
        sa.Column("category_id", sa.String(36), index=True),
        sa.Column("active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- Services ---
    op.create_table(
        "services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- Inventory Items ---
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url_image", sa.Text),
        sa.Column("length", sa.Numeric(12, 2)),
        sa.Column("width", sa.Numeric(12, 2)),
        sa.Column("height", sa.Numeric(12, 2)),
        sa.Column("weight", sa.Numeric(12, 2)),
        sa.Column("category_id", sa.String(36),
                  sa.ForeignKey("inventory_categories.id", ondelete="CASCADE"),
                  index=True, nullable=False),
        sa.Column("active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- Providers ---
    op.create_table(
        "providers",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("email", sa.String(255), index=True),
        sa.Column("name", sa.String(255)),
        sa.Column("phone", sa.String(64)),
        sa.Column("rfc", sa.String(32)),
        sa.Column("address", sa.Text),
        sa.Column("active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- Trucks ---
    op.create_table(
        "trucks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(128),
                  sa.ForeignKey("providers.id", ondelete="CASCADE"),
                  index=True, nullable=False),
        sa.Column("brand", sa.String(128)),
        sa.Column("model", sa.String(128)),
        sa.Column("year", sa.Integer),
        sa.Column("plates", sa.String(32), index=True),
        sa.Column("capacity_kg", sa.Numeric(12, 2)),
        sa.Column("capacity_m3", sa.Numeric(12, 2)),
        sa.Column("active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- Salers ---
    op.create_table(
        "salers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(64)),
        sa.Column("commission_pct", sa.Numeric(5, 2)),
        sa.Column("active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- Auctions ---
    op.create_table(
        "auctions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("quotation_id", sa.String(36),
                  sa.ForeignKey("quotations.id", ondelete="CASCADE"),
                  index=True, nullable=False),
        sa.Column("provider_id", sa.String(128), index=True, nullable=False),
        sa.Column("price_load", sa.Numeric(12, 2), default=0, nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), default=0, nullable=False),
        sa.Column("mobbit_fee", sa.Numeric(12, 2), default=0, nullable=False),
        sa.Column("iva", sa.Numeric(12, 2), default=0, nullable=False),
        sa.Column("transaction_fee", sa.Numeric(12, 2), default=0, nullable=False),
        sa.Column("total", sa.Numeric(12, 2), default=0, nullable=False),
        sa.Column("cash_on_delivery_provider", sa.Numeric(12, 2)),
        sa.Column("cash_on_delivery_mobbit", sa.Numeric(12, 2)),
        sa.Column("people", sa.String(64)),
        sa.Column("id_truck", sa.String(36)),
        sa.Column("state", sa.String(32), default="PENDING", index=True, nullable=False),
        sa.Column("services", postgresql.JSONB),
        sa.Column("products", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("quotation_id", "provider_id", name="uq_auction_quotation_provider"),
    )

    # --- Preferences ---
    op.create_table(
        "preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("auction_id", sa.String(36),
                  sa.ForeignKey("auctions.id", ondelete="CASCADE"),
                  index=True, nullable=False),
        sa.Column("mp_id", sa.String(128), index=True),
        sa.Column("init_point", sa.Text),
        sa.Column("sandbox_init_point", sa.Text),
        sa.Column("date_created", sa.String(64)),
        sa.Column("client_id", sa.String(64)),
        sa.Column("collector_id", sa.String(64)),
        sa.Column("operation_type", sa.String(32)),
        sa.Column("items", sa.Text),
        sa.Column("payer", sa.Text),
        sa.Column("shipment", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # --- Payments ---
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("quotation_id", sa.String(36),
                  sa.ForeignKey("quotations.id", ondelete="CASCADE"),
                  index=True, nullable=False),
        sa.Column("auction_id", sa.String(36),
                  sa.ForeignKey("auctions.id", ondelete="SET NULL"), index=True),
        sa.Column("type", sa.String(32), index=True, nullable=False),
        sa.Column("state", sa.String(32), default="PENDING", index=True, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(8), default="MXN", nullable=False),
        sa.Column("mp_payment_id", sa.String(128), index=True),
        sa.Column("mp_preference_id", sa.String(128)),
        sa.Column("mp_status", sa.String(64)),
        sa.Column("mp_status_detail", sa.String(128)),
        sa.Column("raw_payload", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("preferences")
    op.drop_table("auctions")
    op.drop_table("salers")
    op.drop_table("trucks")
    op.drop_table("providers")
    op.drop_table("inventory_items")
    op.drop_table("services")
    op.drop_table("products")
    op.drop_table("inventory_categories")
    op.drop_table("quotations")
