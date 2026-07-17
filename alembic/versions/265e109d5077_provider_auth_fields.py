"""provider auth fields

Revision ID: 265e109d5077
Revises: 0004_stripe_replacement
Create Date: 2026-07-15 20:37:40.411867

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '265e109d5077'
down_revision: str | None = '0004_stripe_replacement'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new columns to providers (all nullable except kyc_status which needs
    # a two-step add to handle existing rows).
    op.add_column('providers', sa.Column('company_name', sa.String(length=255), nullable=True))
    op.add_column('providers', sa.Column('password_hash', sa.String(length=256), nullable=True))
    op.add_column('providers', sa.Column('verification_token', sa.String(length=512), nullable=True))
    op.add_column('providers', sa.Column('verified_at', sa.DateTime(), nullable=True))
    # kyc_status: add as nullable first, set default for existing rows, then NOT NULL
    op.add_column('providers', sa.Column('kyc_status', sa.String(length=32), nullable=True))
    op.execute("UPDATE providers SET kyc_status = 'NOT_STARTED' WHERE kyc_status IS NULL")
    op.alter_column('providers', 'kyc_status', nullable=False)
    # email unique constraint — deduplicate first, then create unique index
    op.create_index(op.f('ix_providers_kyc_status'), 'providers', ['kyc_status'], unique=False)
    op.drop_index(op.f('ix_providers_email'), table_name='providers')
    op.execute(
        "UPDATE providers SET email = NULL WHERE email IN ("
        "SELECT email FROM providers WHERE email IS NOT NULL "
        "GROUP BY email HAVING COUNT(*) > 1"
        ")"
    )
    op.create_index(op.f('ix_providers_email'), 'providers', ['email'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_providers_kyc_status'), table_name='providers')
    op.drop_index(op.f('ix_providers_email'), table_name='providers')
    op.create_index(op.f('ix_providers_email'), 'providers', ['email'], unique=False)
    op.drop_column('providers', 'kyc_status')
    op.drop_column('providers', 'verified_at')
    op.drop_column('providers', 'verification_token')
    op.drop_column('providers', 'password_hash')
    op.drop_column('providers', 'company_name')
