"""provider documents KYC

Revision ID: 51d59168fd89
Revises: 265e109d5077
Create Date: 2026-07-15 21:11:37.154195

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '51d59168fd89'
down_revision: str | None = '265e109d5077'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
        op.create_table('provider_documents',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('provider_id', sa.String(length=128), nullable=False),
            sa.Column('doc_type', sa.String(length=32), nullable=False),
            sa.Column('file_path', sa.Text(), nullable=False),
            sa.Column('original_name', sa.String(length=255), nullable=True),
            sa.Column('uploaded_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['provider_id'], ['providers.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_provider_documents_provider_id'), 'provider_documents', ['provider_id'], unique=False)


def downgrade() -> None:
        op.drop_index(op.f('ix_provider_documents_provider_id'), table_name='provider_documents')
        op.drop_table('provider_documents')
