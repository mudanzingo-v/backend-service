"""auction admin_budget + provider_note

Revision ID: 0003_auction_admin_budget
Revises: 0002_state_machine_v2
Create Date: 2026-06-17

Phase 2.3 / Auction flow: add the admin-suggested price and the
provider's note to the auction table.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_auction_admin_budget"
down_revision: str | None = "0002_state_machine_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auctions",
        sa.Column("admin_budget", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "auctions",
        sa.Column("provider_note", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auctions", "provider_note")
    op.drop_column("auctions", "admin_budget")
