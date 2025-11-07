"""add resolutions table

Revision ID: 0002_resolutions
Revises: 0001_initial
Create Date: 2024-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_resolutions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resolutions",
        sa.Column("condition_id", sa.String(length=66), primary_key=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'conditional_tokens'")),
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
            server_onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_resolutions_block_number", "resolutions", ["block_number"])


def downgrade() -> None:
    op.drop_index("ix_resolutions_block_number", table_name="resolutions")
    op.drop_table("resolutions")
