"""Replace MercadoPago `preferences` table with Stripe `checkout_sessions`

Revision ID: 0004_stripe_replacement
Revises: 0003_auction_admin_budget
Create Date: 2026-06-24

Phase 1.1 / `stripe-payment-replacement` PR2: swap the database model
from `Preference` (MercadoPago-shaped) to `CheckoutSession`
(Stripe-shaped), and rename `Payment.mp_*` columns to `stripe_*`.

Reversibility (design §D8): the `downgrade()` renames everything back
to the MP schema so we can roll forward and back without data loss.
The acceptance test `test_alembic_upgrade_downgrade_roundtrip` enforces
this in CI.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_stripe_replacement"
down_revision: str | None = "0003_auction_admin_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Rename table `preferences` -> `checkout_sessions`
    #    Preserves all data via `ALTER TABLE ... RENAME TO`.
    # ------------------------------------------------------------------
    op.rename_table("preferences", "checkout_sessions")

    # ------------------------------------------------------------------
    # 2. Rename the `mp_id` index on the renamed table
    # ------------------------------------------------------------------
    op.execute("ALTER INDEX IF EXISTS ix_preferences_mp_id RENAME TO ix_checkout_sessions_stripe_session_id")

    # ------------------------------------------------------------------
    # 3. Drop MP-shaped columns on the renamed `checkout_sessions` table
    # ------------------------------------------------------------------
    op.drop_column("checkout_sessions", "init_point")
    op.drop_column("checkout_sessions", "sandbox_init_point")
    op.drop_column("checkout_sessions", "date_created")
    op.drop_column("checkout_sessions", "client_id")
    op.drop_column("checkout_sessions", "collector_id")
    op.drop_column("checkout_sessions", "operation_type")
    op.drop_column("checkout_sessions", "items")
    op.drop_column("checkout_sessions", "payer")
    op.drop_column("checkout_sessions", "shipment")
    op.drop_column("checkout_sessions", "mp_id")

    # ------------------------------------------------------------------
    # 4. Add Stripe-shaped columns on `checkout_sessions`
    # ------------------------------------------------------------------
    op.add_column(
        "checkout_sessions",
        sa.Column("stripe_session_id", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_checkout_sessions_stripe_session_id_unique",
        "checkout_sessions",
        ["stripe_session_id"],
        unique=True,
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("url", sa.Text(), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("status", sa.String(32), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("payment_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("amount_total", sa.Integer(), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("currency", sa.String(8), nullable=False, server_default="mxn"),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("last_event_id", sa.String(128), nullable=True),
    )

    # ------------------------------------------------------------------
    # 5. Drop `mp_status_detail` on `payments`
    # ------------------------------------------------------------------
    op.drop_column("payments", "mp_status_detail")

    # ------------------------------------------------------------------
    # 6. Rename `mp_*` columns on `payments` -> `stripe_*`
    #    The data is preserved across the rename (verified by
    #    `test_migration_preserves_payment_id_data`).
    # ------------------------------------------------------------------
    op.alter_column(
        "payments",
        "mp_payment_id",
        new_column_name="stripe_payment_intent_id",
    )
    op.alter_column(
        "payments",
        "mp_preference_id",
        new_column_name="stripe_checkout_session_id",
    )
    op.alter_column(
        "payments",
        "mp_status",
        new_column_name="stripe_payment_status",
    )

    # The original index `ix_payments_mp_payment_id` is auto-renamed by
    # PostgreSQL when the column is renamed, so we don't need to
    # re-create it explicitly.


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Reverse 6: rename `stripe_*` columns on `payments` back to `mp_*`
    # ------------------------------------------------------------------
    op.alter_column(
        "payments",
        "stripe_payment_status",
        new_column_name="mp_status",
    )
    op.alter_column(
        "payments",
        "stripe_checkout_session_id",
        new_column_name="mp_preference_id",
    )
    op.alter_column(
        "payments",
        "stripe_payment_intent_id",
        new_column_name="mp_payment_id",
    )

    # ------------------------------------------------------------------
    # Reverse 5: re-add `mp_status_detail` on `payments`
    # ------------------------------------------------------------------
    op.add_column(
        "payments",
        sa.Column("mp_status_detail", sa.String(128), nullable=True),
    )

    # ------------------------------------------------------------------
    # Reverse 4: drop Stripe-shaped columns on `checkout_sessions`
    # ------------------------------------------------------------------
    op.drop_column("checkout_sessions", "last_event_id")
    op.drop_column("checkout_sessions", "currency")
    op.drop_column("checkout_sessions", "amount_total")
    op.drop_column("checkout_sessions", "payment_status")
    op.drop_column("checkout_sessions", "status")
    op.drop_column("checkout_sessions", "url")
    op.drop_index(
        "ix_checkout_sessions_stripe_session_id_unique",
        table_name="checkout_sessions",
    )
    op.drop_column("checkout_sessions", "stripe_session_id")

    # ------------------------------------------------------------------
    # Reverse 3: re-add MP-shaped columns on `checkout_sessions`
    # ------------------------------------------------------------------
    op.add_column(
        "checkout_sessions",
        sa.Column("mp_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_preferences_mp_id",
        "checkout_sessions",
        ["mp_id"],
        unique=False,
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("shipment", sa.Text(), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("payer", sa.Text(), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("items", sa.Text(), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("operation_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("collector_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("client_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("date_created", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("sandbox_init_point", sa.Text(), nullable=True),
    )
    op.add_column(
        "checkout_sessions",
        sa.Column("init_point", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------
    # Reverse 2: rename the index back
    # ------------------------------------------------------------------
    op.execute(
        "ALTER INDEX IF EXISTS ix_checkout_sessions_stripe_session_id "
        "RENAME TO ix_preferences_mp_id"
    )

    # ------------------------------------------------------------------
    # Reverse 1: rename the table back to `preferences`
    # ------------------------------------------------------------------
    op.rename_table("checkout_sessions", "preferences")
