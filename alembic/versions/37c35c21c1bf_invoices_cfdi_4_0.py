"""invoices CFDI 4.0

Revision ID: 37c35c21c1bf
Revises: 51d59168fd89
Create Date: 2026-07-15 21:24:15.341022

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '37c35c21c1bf'
down_revision: Union[str, None] = '51d59168fd89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('invoices',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('payment_id', sa.String(length=36), nullable=False),
        sa.Column('quotation_id', sa.String(length=36), nullable=False),
        sa.Column('rfc_emisor', sa.String(length=13), nullable=False),
        sa.Column('rfc_receptor', sa.String(length=13), nullable=False),
        sa.Column('cfdi_use', sa.String(length=8), nullable=False),
        sa.Column('payment_method', sa.String(length=8), nullable=False),
        sa.Column('subtotal', sa.Numeric(12, 2), nullable=False),
        sa.Column('iva', sa.Numeric(12, 2), nullable=False),
        sa.Column('total', sa.Numeric(12, 2), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('cfdi_uuid', sa.String(length=64), nullable=True),
        sa.Column('pdf_url', sa.Text(), nullable=True),
        sa.Column('xml_url', sa.Text(), nullable=True),
        sa.Column('stamped_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['quotation_id'], ['quotations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cfdi_uuid'),
    )
    op.create_index(op.f('ix_invoices_payment_id'), 'invoices', ['payment_id'], unique=False)
    op.create_index(op.f('ix_invoices_quotation_id'), 'invoices', ['quotation_id'], unique=False)
    op.create_index(op.f('ix_invoices_status'), 'invoices', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_invoices_status'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_quotation_id'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_payment_id'), table_name='invoices')
    op.drop_table('invoices')
