"""Add indexes to speed up market/resolution lookups."""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_add_market_resolution_indexes"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_markets_resolved_at", "markets", ["resolved_at"], unique=False)
    op.create_index("ix_markets_event_resolved", "markets", ["event_id", "resolved_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_markets_event_resolved", table_name="markets")
    op.drop_index("ix_markets_resolved_at", table_name="markets")
