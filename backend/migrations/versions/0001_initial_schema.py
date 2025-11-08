"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2024-11-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False, unique=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("slug", sa.String(length=256), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("metadata_uri", sa.String(length=512), nullable=True),
        sa.Column("oracle", sa.String(length=64), nullable=False),
        sa.Column("factory", sa.String(length=64), nullable=True),
        sa.Column("market_address", sa.String(length=64), nullable=True, unique=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="commit"),
        sa.Column("outcomes", sa.JSON(), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("rake_bps", sa.Integer(), nullable=True),
        sa.Column("condition_id", sa.String(length=66), nullable=True),
        sa.Column("question_id", sa.String(length=128), nullable=True),
        sa.Column("outcome_prices", sa.JSON(), nullable=True),
        sa.Column("image_url", sa.String(length=512), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("uma_resolution_status", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_markets_status_category", "markets", ["status", "category"])
    op.create_index("ix_markets_slug", "markets", ["slug"])
    op.create_index("ix_markets_condition_id", "markets", ["condition_id"])
    op.create_index("ix_markets_event_id", "markets", ["event_id"], unique=True)

    op.create_table(
        "resolutions",
        sa.Column("condition_id", sa.String(length=66), primary_key=True, nullable=False),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'conditional_tokens'"),
        ),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("payouts", sa.JSON(), nullable=False),
        sa.Column("winners", sa.JSON(), nullable=True),
        sa.Column("outcomes", sa.JSON(), nullable=True),
        sa.Column("oracle", sa.String(length=64), nullable=True),
        sa.Column("question_id", sa.String(length=66), nullable=True),
        sa.Column("transaction_hash", sa.String(length=66), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_resolutions_block_number", "resolutions", ["block_number"])

    op.create_table(
        "schema_versions",
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("schema_versions")
    op.drop_index("ix_resolutions_block_number", table_name="resolutions")
    op.drop_table("resolutions")
    op.drop_index("ix_markets_event_id", table_name="markets")
    op.drop_index("ix_markets_condition_id", table_name="markets")
    op.drop_index("ix_markets_slug", table_name="markets")
    op.drop_index("ix_markets_status_category", table_name="markets")
    op.drop_table("markets")
