"""state machine v2 + wizard progress

Revision ID: 0002_state_machine_v2
Revises: 0001_initial
Create Date: 2026-06-16

Phase 0 / D3: separate the quotation lifecycle state (state) from the
B2C wizard progress (wizard_step, wizard_complete).

Also migrates existing data:
  state='FILLED' | 'quoted' → state='QUOTED', wizard_complete=true
  state='step_3'          → state='DRAFT',  wizard_step=3
  state='step_4'          → state='DRAFT',  wizard_step=4
  state='step_6'          → state='DRAFT',  wizard_step=6
  state=NULL or other     → state stays as-is, wizard_step=NULL, wizard_complete=false
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_state_machine_v2"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- 1. Schema: add columns ----
    op.add_column(
        "quotations",
        sa.Column("wizard_step", sa.Integer, nullable=True),
    )
    op.add_column(
        "quotations",
        sa.Column(
            "wizard_complete",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_quotations_wizard_step",
        "quotations",
        ["wizard_step"],
    )
    op.create_index(
        "idx_quotations_state",
        "quotations",
        ["state"],
    )

    # ---- 2. Data migration: state + wizard_step ----
    # 2a. Already-published quotations (the provider sees them) → QUOTED + complete
    op.execute("""
        UPDATE quotations SET
            state = 'QUOTED',
            wizard_complete = true
        WHERE state IN ('FILLED', 'quoted')
    """)

    # 2b. Mid-wizard records (data from the B2C wizard in flight)
    op.execute("""
        UPDATE quotations SET
            state = 'DRAFT',
            wizard_step = 3
        WHERE state = 'step_3'
    """)
    op.execute("""
        UPDATE quotations SET
            state = 'DRAFT',
            wizard_step = 4
        WHERE state = 'step_4'
    """)
    op.execute("""
        UPDATE quotations SET
            state = 'DRAFT',
            wizard_step = 6
        WHERE state = 'step_6'
    """)

    # 2c. NULL or unknown values: keep state as-is, leave wizard_step=NULL,
    #     wizard_complete=false. Admins can update later via the new
    #     POST /quotation/{id}/publish endpoint.


def downgrade() -> None:
    # Reverse the data migration: best-effort (we lose wizard_step info)
    op.execute("""
        UPDATE quotations SET state = 'FILLED' WHERE state = 'QUOTED'
    """)
    op.execute("""
        UPDATE quotations SET
            state = 'step_' || wizard_step::text
        WHERE state = 'DRAFT' AND wizard_step IS NOT NULL
    """)

    op.drop_index("idx_quotations_state", table_name="quotations")
    op.drop_index("idx_quotations_wizard_step", table_name="quotations")
    op.drop_column("quotations", "wizard_complete")
    op.drop_column("quotations", "wizard_step")
