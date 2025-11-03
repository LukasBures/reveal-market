"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2024-07-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False, unique=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("metadata_uri", sa.String(length=512), nullable=True),
        sa.Column("oracle", sa.String(length=64), nullable=False),
        sa.Column("factory", sa.String(length=64), nullable=True),
        sa.Column("market_address", sa.String(length=64), nullable=True, unique=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="commit"),
        sa.Column("outcomes", sa.JSON(), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_markets_status_category",
        "markets",
        ["status", "category"],
    )
    op.create_index("ix_markets_event_id", "markets", ["event_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_markets_status_category", table_name="markets")
    op.drop_table("markets")
