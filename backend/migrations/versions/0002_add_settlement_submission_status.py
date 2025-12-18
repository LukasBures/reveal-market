"""Add settlement submission status fields.

Revision ID: 0002_settlement_status
Revises: 0001_initial_schema
Create Date: 2025-01-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_settlement_status"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settlements",
        sa.Column("submission_status", sa.String(length=32), nullable=False, server_default="none"),
    )
    op.add_column("settlements", sa.Column("submission_error", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_settlements_submission_status",
        "settlements",
        "submission_status IN ('none','queued','processing','submitted','failed')",
    )
    # Drop the server default now that existing rows are initialised.
    op.alter_column("settlements", "submission_status", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_settlements_submission_status", "settlements", type_="check")
    op.drop_column("settlements", "submission_error")
    op.drop_column("settlements", "submission_status")
