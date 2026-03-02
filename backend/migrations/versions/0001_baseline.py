"""baseline schema v1 — optimized

Revision ID: 0001_baseline
Revises:
Create Date: 2026-03-02 00:00:00.000000

FK Strategy Notes:
    - ``markets.id`` (Integer, auto-increment): Internal numeric PK used by child tables
      for efficient joins and indexing.
    - ``markets.event_id`` (String): External Polymarket identifier used as a stable
      cross-service reference. Some tables reference ``event_id`` because data originates
      from external sources where only the string ID is known at ingest time.

Key optimizations baked into this schema:
    - All string-identity columns (event_id, condition_id, market_address, group_slug,
      category, event_key) are normalized to lowercase on write via @validates, so no
      functional lower() indexes are needed — standard B-tree indexes are used instead.
    - Float columns replaced with Numeric(32,8) for financial precision.
    - Stored tsvector column + GIN index for full-text search.
    - Composite, partial, and BRIN indexes for hot query patterns.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ────────────────────────────────────────
    # markets
    # ────────────────────────────────────────
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("slug", sa.String(length=256), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("metadata_uri", sa.String(length=512), nullable=True),
        sa.Column("oracle", sa.String(length=64), nullable=False),
        sa.Column("factory", sa.String(length=64), nullable=True),
        sa.Column("onchain_market_id", sa.Integer(), nullable=True),
        sa.Column("market_address", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("group_slug", sa.String(length=256), nullable=True),
        sa.Column("event_key", sa.String(length=256), nullable=True),
        sa.Column("group_position", sa.Integer(), nullable=True),
        sa.Column("rake_bps", sa.Integer(), nullable=True),
        sa.Column("condition_id", sa.String(length=66), nullable=True),
        sa.Column("question_id", sa.String(length=128), nullable=True),
        sa.Column("image_url", sa.String(length=512), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolution_status", sa.String(length=32), nullable=True),
        sa.Column("resolution_reason", sa.String(length=128), nullable=True),
        sa.Column("commits_blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uma_resolution_status", sa.String(length=64), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orders_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_source", sa.String(length=512), nullable=True),
        sa.Column("market_maker", sa.String(length=64), nullable=True),
        sa.Column("order_min_size", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("price_tick_size", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("enable_order_book", sa.Boolean(), nullable=True),
        sa.Column("image_variants", sa.JSON(), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("liquidity_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume_24h_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("orderbook_volume_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("trades_quantity", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('commit','locked','settled','cancelled')", name="ck_markets_status"),
        sa.CheckConstraint(
            "resolution_status IN ('pending_resolution','disputed','final')", name="ck_markets_resolution_status"
        ),
        sa.UniqueConstraint("event_id", name="uq_markets_event_id"),
        sa.UniqueConstraint("onchain_market_id", name="uq_markets_onchain_market_id"),
        sa.UniqueConstraint("market_address", name="uq_markets_market_address"),
    )
    op.create_index("ix_markets_event_id", "markets", ["event_id"])
    op.create_index("ix_markets_status_category", "markets", ["status", "category"])
    op.create_index("ix_markets_slug", "markets", ["slug"])
    op.create_index("ix_markets_condition_id", "markets", ["condition_id"])
    op.create_index("ix_markets_resolution_status", "markets", ["resolution_status"])
    op.create_index("ix_markets_event_key", "markets", ["event_key"])
    op.create_index("ix_markets_group_slug", "markets", ["group_slug"])
    op.create_index("ix_markets_closes_at", "markets", ["closes_at"])
    op.create_index("ix_markets_category", "markets", ["category"])

    # Stored tsvector column + GIN index for full-text search
    op.execute(
        sa.text(
            "ALTER TABLE markets ADD COLUMN search_vector tsvector"
            " GENERATED ALWAYS AS ("
            "   to_tsvector('english',"
            "     coalesce(title, '') || ' ' || coalesce(slug, '') || ' ' ||"
            "     coalesce(category, '') || ' ' || coalesce(oracle, '')"
            "   )"
            " ) STORED"
        )
    )
    op.execute(sa.text("CREATE INDEX ix_markets_search_vector ON markets USING gin(search_vector)"))

    # Partial index: featured markets (very selective)
    op.execute(sa.text("CREATE INDEX ix_markets_featured ON markets (featured) WHERE featured = true"))

    # ────────────────────────────────────────
    # market_outcomes
    # ────────────────────────────────────────
    op.create_table(
        "market_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("outcome_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("price", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("market_id", "outcome_id", name="ux_market_outcomes_market_outcome"),
    )
    op.create_index("ix_market_outcomes_market_id", "market_outcomes", ["market_id"])

    # ────────────────────────────────────────
    # market_tags
    # ────────────────────────────────────────
    op.create_table(
        "market_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("tag", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("market_id", "tag", name="ux_market_tags_market_tag"),
    )
    op.create_index("ix_market_tags_market_id", "market_tags", ["market_id"])

    # ────────────────────────────────────────
    # market_clob_tokens
    # ────────────────────────────────────────
    op.create_table(
        "market_clob_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=True),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("market_id", "token_id", name="ux_market_clob_tokens_market_token"),
    )
    op.create_index("ix_market_clob_tokens_market_id", "market_clob_tokens", ["market_id"])

    # ────────────────────────────────────────
    # market_gamma_metadata
    # ────────────────────────────────────────
    op.create_table(
        "market_gamma_metadata",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("gamma_id", sa.String(length=64), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=256), nullable=True),
        sa.Column("resolution_source", sa.String(length=512), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("image", sa.String(length=512), nullable=True),
        sa.Column("icon", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=True),
        sa.Column("restricted", sa.Boolean(), nullable=True),
        sa.Column("group_item_title", sa.String(length=256), nullable=True),
        sa.Column("group_item_threshold", sa.String(length=64), nullable=True),
        sa.Column("question_id", sa.String(length=128), nullable=True),
        sa.Column("enable_order_book", sa.Boolean(), nullable=True),
        sa.Column("order_price_min_tick_size", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("order_min_size", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume_num", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume1mo", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume_clob", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("liquidity", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("liquidity_num", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("liquidity_clob", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("clob_token_id_yes", sa.String(length=128), nullable=True),
        sa.Column("clob_token_id_no", sa.String(length=128), nullable=True),
        sa.Column("accepting_orders", sa.Boolean(), nullable=True),
        sa.Column("accepting_orders_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("group_slug", sa.String(length=256), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=True),
        sa.Column("best_bid", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("best_ask", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("spread", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_market_gamma_metadata_group_slug", "market_gamma_metadata", ["group_slug"])

    # ────────────────────────────────────────
    # resolutions
    # ────────────────────────────────────────
    op.create_table(
        "resolutions",
        sa.Column("condition_id", sa.String(length=66), primary_key=True, nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=True),
        sa.Column("event_id", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="conditional_tokens"),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("payouts", sa.JSON(), nullable=False),
        sa.Column("winners", sa.JSON(), nullable=True),
        sa.Column("oracle", sa.String(length=64), nullable=True),
        sa.Column("question_id", sa.String(length=66), nullable=True),
        sa.Column("transaction_hash", sa.String(length=66), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("winning_outcome_id", sa.Integer(), nullable=True),
        sa.Column("rake_bps", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["markets.event_id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "market_id IS NOT NULL OR event_id IS NOT NULL",
            name="ck_resolutions_has_market_ref",
        ),
    )
    op.create_index("ix_resolutions_block_number", "resolutions", ["block_number"])
    op.create_index("ix_resolutions_market_id", "resolutions", ["market_id"])
    op.create_index("ix_resolutions_event_id", "resolutions", ["event_id"])

    # ────────────────────────────────────────
    # commitments
    # ────────────────────────────────────────
    op.create_table(
        "commitments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("user_address", sa.String(length=64), nullable=False),
        sa.Column("outcome_id", sa.Integer(), nullable=False),
        sa.Column("amount_wei", sa.BigInteger(), nullable=False),
        sa.Column("payout_wei", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("salt", sa.String(length=66), nullable=True),
        sa.Column("ticket_hash", sa.String(length=66), nullable=False),
        sa.Column("leaf", sa.String(length=66), nullable=False),
        sa.Column("leaf_index", sa.Integer(), nullable=True),
        sa.Column("tx_hash", sa.String(length=66), nullable=True),
        sa.Column("claim_tx_hash", sa.String(length=66), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("market_id", "ticket_hash", name="ux_commitments_market_ticket_hash"),
    )
    op.create_index("ix_commitments_market_id", "commitments", ["market_id"])
    op.create_index("ix_commitments_user_address", "commitments", ["user_address"])
    op.create_index("ix_commitments_claim_tx_hash", "commitments", ["claim_tx_hash"])
    op.create_index("ix_commitments_market_leaf", "commitments", ["market_id", "leaf_index"])
    # Composite: wallet commitment lookups
    op.create_index("ix_commitments_user_market", "commitments", ["user_address", "market_id"])
    # Settlement filtering by winning outcome
    op.create_index("ix_commitments_outcome", "commitments", ["outcome_id"])
    # BRIN: append-only timestamp for range scans
    op.execute(sa.text("CREATE INDEX ix_commitments_created_brin ON commitments USING brin(created_at)"))

    # ────────────────────────────────────────
    # commitment_merkle_paths
    # ────────────────────────────────────────
    op.create_table(
        "commitment_merkle_paths",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("commitment_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("sibling_hash", sa.String(length=66), nullable=False),
        sa.ForeignKeyConstraint(["commitment_id"], ["commitments.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_commitment_merkle_paths_commitment", "commitment_merkle_paths", ["commitment_id"])

    # ────────────────────────────────────────
    # settlements
    # ────────────────────────────────────────
    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("merkle_root", sa.String(length=66), nullable=True),
        sa.Column("commitments_count", sa.Integer(), nullable=True),
        sa.Column("batch_roots", sa.JSON(), nullable=True),
        sa.Column("batch_counts", sa.JSON(), nullable=True),
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
        sa.Column("submission_status", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("submission_error", sa.Text(), nullable=True),
        sa.Column("settlement_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_tx_hash", sa.String(length=66), nullable=True),
        sa.Column("settlement_block_number", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "proof_status IN ('none','pending','generating','requested','generated','failed')",
            name="ck_settlements_proof_status",
        ),
        sa.CheckConstraint(
            "submission_status IN ('none','queued','processing','submitted','failed')",
            name="ck_settlements_submission_status",
        ),
    )
    op.create_index("ix_settlements_market_id", "settlements", ["market_id"])
    op.create_index("ix_settlements_tx_hash", "settlements", ["settlement_tx_hash"])
    op.create_index("ix_settlements_proof_status", "settlements", ["proof_status"])
    op.create_index("ix_settlements_submission_status", "settlements", ["submission_status"])

    # ────────────────────────────────────────
    # schema_versions
    # ────────────────────────────────────────
    op.create_table(
        "schema_versions",
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ────────────────────────────────────────
    # quotes
    # ────────────────────────────────────────
    op.create_table(
        "quotes",
        sa.Column("quote_id", sa.String(length=66), primary_key=True, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="issued"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("stake_zen", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("stake_wei", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("fx_scaled", sa.BigInteger(), nullable=False),
        sa.Column("zen_usd", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("market_id", sa.String(length=128), nullable=True),
        sa.Column("market_address", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("wallet_address", sa.String(length=64), nullable=True),
        sa.Column("outcome_id", sa.Integer(), nullable=True),
        sa.Column("chain_id", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('issued','consumed','expired')", name="ck_quotes_status"),
        sa.ForeignKeyConstraint(["market_id"], ["markets.event_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_quotes_market_id", "quotes", ["market_id"])
    op.create_index("ix_quotes_user_id", "quotes", ["user_id"])
    op.create_index("ix_quotes_wallet_address", "quotes", ["wallet_address"])
    op.create_index(
        "ix_quotes_expires_at_issued", "quotes", ["expires_at"], postgresql_where=sa.text("status = 'issued'")
    )
    op.create_index("ix_quotes_status", "quotes", ["status"])
    op.create_index("ix_quotes_created_at", "quotes", ["created_at"])

    # ────────────────────────────────────────
    # quote_audits
    # ────────────────────────────────────────
    op.create_table(
        "quote_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("quote_id", sa.String(length=66), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("wallet_address", sa.String(length=64), nullable=True),
        sa.Column("market_id", sa.String(length=128), nullable=True),
        sa.Column("market_address", sa.String(length=64), nullable=True),
        sa.Column("outcome_id", sa.Integer(), nullable=True),
        sa.Column("chain_id", sa.BigInteger(), nullable=True),
        sa.Column("stake_zen", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("stake_wei", sa.Numeric(precision=78, scale=0), nullable=True),
        sa.Column("fx_scaled", sa.BigInteger(), nullable=True),
        sa.Column("zen_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.quote_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_quote_audits_quote_id", "quote_audits", ["quote_id"])
    op.create_index("ix_quote_audits_user_id", "quote_audits", ["user_id"])
    op.create_index("ix_quote_audits_wallet_address", "quote_audits", ["wallet_address"])
    op.create_index("ix_quote_audits_market_id", "quote_audits", ["market_id"])
    # BRIN: append-only timestamp for range scans
    op.execute(sa.text("CREATE INDEX ix_quote_audits_created_brin ON quote_audits USING brin(created_at)"))

    # ────────────────────────────────────────
    # factory_events
    # ────────────────────────────────────────
    op.create_table(
        "factory_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factory_address", sa.String(length=64), nullable=False),
        sa.Column("market_address", sa.String(length=64), nullable=True),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["market_address"], ["markets.market_address"], ondelete="SET NULL"),
        sa.UniqueConstraint("factory_address", "event", "tx_hash", name="ux_factory_events_dedupe"),
    )
    op.create_index("ix_factory_events_factory", "factory_events", ["factory_address"])
    op.create_index("ix_factory_events_market", "factory_events", ["market_address"])
    op.create_index("ix_factory_events_tx_hash", "factory_events", ["tx_hash"])

    # ────────────────────────────────────────
    # settlement_receipts
    # ────────────────────────────────────────
    op.create_table(
        "settlement_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("market_address", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("proof_hash", sa.String(length=66), nullable=True),
        sa.Column("batch_index", sa.Integer(), nullable=True),
        sa.Column("public_signals", sa.JSON(), nullable=True),
        sa.Column("prover_version", sa.String(length=64), nullable=True),
        sa.Column("circuit_hash", sa.String(length=66), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proof", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["market_address"], ["markets.market_address"], ondelete="SET NULL"),
        sa.UniqueConstraint("market_id", "request_id", name="ux_settlement_receipts_market_request"),
    )
    op.create_index("ix_settlement_receipts_market_id", "settlement_receipts", ["market_id"])
    op.create_index("ix_settlement_receipts_market_address", "settlement_receipts", ["market_address"])
    op.create_index("ix_settlement_receipts_request", "settlement_receipts", ["request_id"])

    # ────────────────────────────────────────
    # hedger_treasury_snapshots
    # ────────────────────────────────────────
    op.create_table(
        "hedger_treasury_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(length=128), nullable=False),
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
        sa.ForeignKeyConstraint(["market_id"], ["markets.event_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_treasury_market_id", "hedger_treasury_snapshots", ["market_id"])


def downgrade() -> None:
    op.drop_table("hedger_treasury_snapshots")
    op.drop_table("settlement_receipts")
    op.drop_table("factory_events")
    op.drop_table("quote_audits")
    op.drop_table("quotes")
    op.drop_table("schema_versions")
    op.drop_table("settlements")
    op.drop_table("commitment_merkle_paths")
    op.drop_table("commitments")
    op.drop_table("resolutions")
    op.drop_table("market_gamma_metadata")
    op.drop_table("market_clob_tokens")
    op.drop_table("market_tags")
    op.drop_table("market_outcomes")
    op.drop_table("markets")
