"""add hedger treasury snapshots

Revision ID: 0002_hedger_treasury
Revises: 0001_initial_schema
Create Date: 2025-01-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_hedger_treasury"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hedger_treasury_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("stake_zen", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("refund_zen", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("rake_zen", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("payout_profit_usdc", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("borrowed_usdc", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("lp_share_usdc", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("repay_amount_usdc", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("platform_usdc_revenue", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("zen_balance", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("usdc_balance", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_hedger_treasury_snapshots_market_id",
        "hedger_treasury_snapshots",
        ["market_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_hedger_treasury_snapshots_market_id", table_name="hedger_treasury_snapshots")
    op.drop_table("hedger_treasury_snapshots")
