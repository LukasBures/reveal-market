"""add resolution status flags and settlement tx metadata

Revision ID: 0002_resolution_status_flags
Revises: 0001_initial_schema
Create Date: 2025-02-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_resolution_status_flags"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "markets",
        sa.Column(
            "resolution_status",
            sa.String(length=32),
            nullable=False,
            server_default="final",
        ),
    )
    op.add_column(
        "markets",
        sa.Column("resolution_reason", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "markets",
        sa.Column("commits_blocked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_markets_resolution_status",
        "markets",
        "resolution_status IN ('pending_resolution','disputed','final')",
    )
    op.create_index(
        "ix_markets_resolution_status",
        "markets",
        ["resolution_status"],
    )
    op.add_column(
        "settlements",
        sa.Column("settlement_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "settlements",
        sa.Column("settlement_tx_hash", sa.String(length=66), nullable=True),
    )
    op.add_column(
        "settlements",
        sa.Column("settlement_block_number", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_settlements_tx_hash", "settlements", ["settlement_tx_hash"])


def downgrade() -> None:
    op.drop_index("ix_settlements_tx_hash", table_name="settlements")
    op.drop_column("settlements", "settlement_block_number")
    op.drop_column("settlements", "settlement_tx_hash")
    op.drop_column("settlements", "settlement_submitted_at")
    op.drop_index("ix_markets_resolution_status", table_name="markets")
    op.drop_constraint("ck_markets_resolution_status", "markets")
    op.drop_column("markets", "commits_blocked_at")
    op.drop_column("markets", "resolution_reason")
    op.drop_column("markets", "resolution_status")
