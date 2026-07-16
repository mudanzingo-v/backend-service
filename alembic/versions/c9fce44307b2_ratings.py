"""ratings

Revision ID: c9fce44307b2
Revises: 8b5b97b4bc8b
Create Date: 2026-07-16 11:00:21.928374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9fce44307b2"
down_revision: Union[str, None] = "8b5b97b4bc8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ratings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("auction_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("quotation_id", sa.String(36), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["auction_id"], ["auctions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quotation_id"], ["quotations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ratings_auction_id"), "ratings", ["auction_id"], unique=True)
    op.create_index(op.f("ix_ratings_provider_id"), "ratings", ["provider_id"], unique=False)
    op.create_index(op.f("ix_ratings_quotation_id"), "ratings", ["quotation_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ratings_quotation_id"), table_name="ratings")
    op.drop_index(op.f("ix_ratings_provider_id"), table_name="ratings")
    op.drop_index(op.f("ix_ratings_auction_id"), table_name="ratings")
    op.drop_table("ratings")
