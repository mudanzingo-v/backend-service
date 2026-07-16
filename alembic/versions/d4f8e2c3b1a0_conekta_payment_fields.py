"""conekta payment fields — SPEI / OXXO support

Adds ``conekta_order_id`` and ``conekta_payment_method`` columns to the
``payments`` table so Conekta transactions can be tracked alongside
existing Stripe transactions.

Revision ID: d4f8e2c3b1a0
Revises: c9fce44307b2
Create Date: 2026-07-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f8e2c3b1a0"
down_revision: Union[str, None] = "c9fce44307b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("conekta_order_id", sa.String(128), nullable=True))
    op.create_index(
        op.f("ix_payments_conekta_order_id"),
        "payments",
        ["conekta_order_id"],
        unique=False,
    )
    op.add_column(
        "payments",
        sa.Column("conekta_payment_method", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_payments_conekta_order_id"), table_name="payments")
    op.drop_column("payments", "conekta_payment_method")
    op.drop_column("payments", "conekta_order_id")
