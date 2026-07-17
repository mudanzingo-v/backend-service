"""provider availability scheduling

Revision ID: 8b5b97b4bc8b
Revises: 71aa4c438409
Create Date: 2026-07-16 10:45:16.926467

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8b5b97b4bc8b"
down_revision: str | None = "71aa4c438409"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_availability",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("slots", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "date", name="uq_provider_date"),
    )
    op.create_index(
        op.f("ix_provider_availability_provider_id"),
        "provider_availability", ["provider_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_provider_availability_provider_id"),
        table_name="provider_availability",
    )
    op.drop_table("provider_availability")
