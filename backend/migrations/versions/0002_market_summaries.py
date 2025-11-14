"""add market summary fields

Revision ID: 0002_market_summaries
Revises: 0001_initial_schema
Create Date: 2024-12-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_market_summaries"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("markets", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("markets", sa.Column("summary_source", sa.String(length=64), nullable=True))
    op.add_column("markets", sa.Column("summary_model", sa.String(length=64), nullable=True))
    op.add_column("markets", sa.Column("summary_metadata", sa.JSON(), nullable=True))
    op.add_column("markets", sa.Column("summary_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("markets", sa.Column("summary_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("markets", "summary_requested_at")
    op.drop_column("markets", "summary_checked_at")
    op.drop_column("markets", "summary_metadata")
    op.drop_column("markets", "summary_model")
    op.drop_column("markets", "summary_source")
    op.drop_column("markets", "summary")
