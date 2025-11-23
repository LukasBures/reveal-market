"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2024-11-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Core market tables
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
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_source", sa.String(length=64), nullable=True),
        sa.Column("summary_model", sa.String(length=64), nullable=True),
        sa.Column("summary_metadata", sa.JSON(), nullable=True),
        sa.Column("summary_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rake_bps", sa.Integer(), nullable=True),
        sa.Column("condition_id", sa.String(length=66), nullable=True),
        sa.Column("question_id", sa.String(length=128), nullable=True),
        sa.Column("outcome_prices", sa.JSON(), nullable=True),
        sa.Column("image_url", sa.String(length=512), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("uma_resolution_status", sa.String(length=64), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orders_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_source", sa.String(length=512), nullable=True),
        sa.Column("market_maker", sa.String(length=64), nullable=True),
        sa.Column("order_min_size", sa.Float(), nullable=True),
        sa.Column("price_tick_size", sa.Float(), nullable=True),
        sa.Column("enable_order_book", sa.Boolean(), nullable=True),
        sa.Column("clob_token_ids", sa.JSON(), nullable=True),
        sa.Column("image_variants", sa.JSON(), nullable=True),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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

    # Commitments and settlement data for zk-proof generation
    op.create_table(
        "commitments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("user_address", sa.String(length=64), nullable=False),
        sa.Column("outcome_id", sa.Integer(), nullable=False),
        sa.Column("amount_wei", sa.BigInteger(), nullable=False),
        sa.Column("salt", sa.String(length=66), nullable=True),
        sa.Column("ticket_hash", sa.String(length=66), nullable=False),
        sa.Column("leaf", sa.String(length=66), nullable=False),
        sa.Column("leaf_index", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_commitments_market_id", "commitments", ["market_id"])
    op.create_index("ix_commitments_market_user", "commitments", ["market_id", "user_address"])

    op.create_table(
        "commitment_merkle_paths",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("commitment_id", sa.BigInteger(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("sibling_hash", sa.String(length=66), nullable=False),
    )
    op.create_index(
        "ix_commitment_merkle_paths_commitment_level",
        "commitment_merkle_paths",
        ["commitment_id", "level"],
    )

    op.create_table(
        "settlements",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("merkle_root", sa.String(length=66), nullable=True),
        sa.Column("commitments_count", sa.Integer(), nullable=True),
        sa.Column("pool_total_yes", sa.BigInteger(), nullable=True),
        sa.Column("pool_total_no", sa.BigInteger(), nullable=True),
        sa.Column("total_escrow", sa.BigInteger(), nullable=True),
        sa.Column("total_liability", sa.BigInteger(), nullable=True),
        sa.Column("rake_bps", sa.Integer(), nullable=True),
        sa.Column("winning_outcome_id", sa.Integer(), nullable=True),
        sa.Column("circuit_hash", sa.String(length=66), nullable=True),
        sa.Column("proof_status", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("proof_request_id", sa.String(length=128), nullable=True),
        sa.Column("proof_hash", sa.String(length=66), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_settlements_market_id", "settlements", ["market_id"])
    op.create_index("ix_settlements_proof_status", "settlements", ["proof_status"])

    op.create_table(
        "schema_versions",
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_index("ix_settlements_proof_status", table_name="settlements")
    op.drop_index("ix_settlements_market_id", table_name="settlements")
    op.drop_table("settlements")
    op.drop_index("ix_commitment_merkle_paths_commitment_level", table_name="commitment_merkle_paths")
    op.drop_table("commitment_merkle_paths")
    op.drop_index("ix_commitments_market_user", table_name="commitments")
    op.drop_index("ix_commitments_market_id", table_name="commitments")
    op.drop_table("commitments")
    op.drop_table("schema_versions")
    op.drop_index("ix_resolutions_block_number", table_name="resolutions")
    op.drop_table("resolutions")
    op.drop_index("ix_markets_event_id", table_name="markets")
    op.drop_index("ix_markets_condition_id", table_name="markets")
    op.drop_index("ix_markets_slug", table_name="markets")
    op.drop_index("ix_markets_status_category", table_name="markets")
    op.drop_table("markets")
