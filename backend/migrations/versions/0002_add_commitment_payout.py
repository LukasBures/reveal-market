"""add commitment payout amount

Revision ID: 0002_add_commitment_payout
Revises: 0001_initial_schema
Create Date: 2025-02-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_add_commitment_payout"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "commitments",
        sa.Column("payout_wei", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("commitments", "payout_wei")
