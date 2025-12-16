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


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    is_pg = _is_postgres()
    if is_pg:
        # Needed for trigram GIN index on VARCHAR columns.
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
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
        sa.Column("onchain_market_id", sa.Integer(), nullable=True, unique=True),
        sa.Column("market_address", sa.String(length=64), nullable=True, unique=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="commit"),
        sa.Column("gamma_raw", sa.JSON(), nullable=True),
        sa.Column("group_slug", sa.String(length=256), nullable=True),
        sa.Column("group_position", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_source", sa.String(length=64), nullable=True),
        sa.Column("summary_model", sa.String(length=64), nullable=True),
        sa.Column("summary_metadata", sa.JSON(), nullable=True),
        sa.Column("summary_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("liquidity_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume_24h_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("orderbook_volume_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("trades_quantity", sa.Integer(), nullable=True),
        sa.Column("rake_bps", sa.Integer(), nullable=True),
        sa.Column("condition_id", sa.String(length=66), nullable=True),
        sa.Column("question_id", sa.String(length=128), nullable=True),
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
        sa.Column("image_variants", sa.JSON(), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_status", sa.String(length=32), nullable=False, server_default="final"),
        sa.Column("resolution_reason", sa.String(length=128), nullable=True),
        sa.Column("commits_blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('commit','locked','settled','cancelled')",
            name="ck_markets_status",
        ),
        sa.CheckConstraint(
            "resolution_status IN ('pending_resolution','disputed','final')",
            name="ck_markets_resolution_status",
        ),
    )
    op.create_index("ix_markets_status_category", "markets", ["status", "category"])
    op.create_index("ix_markets_slug", "markets", ["slug"])
    op.create_index("ix_markets_condition_id", "markets", ["condition_id"])
    op.create_index("ix_markets_group_slug", "markets", ["group_slug"])
    op.create_index("ix_markets_featured", "markets", ["featured"])
    op.create_index("ix_markets_event_id", "markets", ["event_id"], unique=True)
    op.create_index("ix_markets_resolved_at", "markets", ["resolved_at"])
    op.create_index("ix_markets_event_resolved", "markets", ["event_id", "resolved_at"])
    op.create_index("ix_markets_resolution_status", "markets", ["resolution_status"])
    # Normalize tags and clob token ids instead of storing JSON blobs
    op.create_table(
        "market_tags",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag", sa.String(length=128), nullable=False),
        sa.UniqueConstraint("market_id", "tag", name="ux_market_tags_market_tag"),
    )
    op.create_index("ix_market_tags_market_id", "market_tags", ["market_id"])
    if is_pg:
        op.create_index(
            "ix_market_tags_gin",
            "market_tags",
            ["tag"],
            postgresql_using="gin",
            postgresql_ops={"tag": "gin_trgm_ops"},
        )

    op.create_table(
        "market_clob_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=True),
        sa.UniqueConstraint("market_id", "token_id", name="ux_market_clob_tokens_market_token"),
    )
    op.create_index("ix_market_clob_tokens_market_id", "market_clob_tokens", ["market_id"])

    op.create_table(
        "market_outcomes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("price", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("market_id", "outcome_id", name="ux_market_outcomes_market_outcome"),
    )
    op.create_index("ix_market_outcomes_market_id", "market_outcomes", ["market_id"])

    op.create_table(
        "market_gamma_metadata",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
        sa.Column("gamma_id", sa.String(length=64), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=256), nullable=True),
        sa.Column("resolution_source", sa.String(length=512), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("image", sa.String(length=512), nullable=True),
        sa.Column("icon", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("liquidity", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=True),
        sa.Column("market_maker_address", sa.String(length=128), nullable=True),
        sa.Column("created_at_raw", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_raw", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", sa.String(length=128), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.Column("restricted", sa.Boolean(), nullable=True),
        sa.Column("group_item_title", sa.String(length=256), nullable=True),
        sa.Column("group_item_threshold", sa.String(length=64), nullable=True),
        sa.Column("group_slug", sa.String(length=256), nullable=True),
        sa.Column("question_id", sa.String(length=128), nullable=True),
        sa.Column("enable_order_book", sa.Boolean(), nullable=True),
        sa.Column("order_price_min_tick_size", sa.Float(), nullable=True),
        sa.Column("order_min_size", sa.Float(), nullable=True),
        sa.Column("volume_num", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("liquidity_num", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("end_date_iso", sa.String(length=64), nullable=True),
        sa.Column("start_date_iso", sa.String(length=64), nullable=True),
        sa.Column("has_reviewed_dates", sa.Boolean(), nullable=True),
        sa.Column("volume1mo", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume1yr", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("clob_token_id_yes", sa.String(length=128), nullable=True),
        sa.Column("clob_token_id_no", sa.String(length=128), nullable=True),
        sa.Column("uma_bond", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("uma_reward", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume1mo_clob", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume1yr_clob", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume_clob", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("liquidity_clob", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("custom_liveness", sa.Integer(), nullable=True),
        sa.Column("accepting_orders", sa.Boolean(), nullable=True),
        sa.Column("neg_risk", sa.Boolean(), nullable=True),
        sa.Column("neg_risk_market_id", sa.String(length=128), nullable=True),
        sa.Column("neg_risk_request_id", sa.String(length=128), nullable=True),
        sa.Column("ready", sa.Boolean(), nullable=True),
        sa.Column("funded", sa.Boolean(), nullable=True),
        sa.Column("accepting_orders_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("competitive", sa.Float(), nullable=True),
        sa.Column("pagerduty_enabled", sa.Boolean(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("rewards_min_size", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("rewards_max_spread", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("one_day_price_change", sa.Float(), nullable=True),
        sa.Column("one_week_price_change", sa.Float(), nullable=True),
        sa.Column("one_month_price_change", sa.Float(), nullable=True),
        sa.Column("last_trade_price", sa.Float(), nullable=True),
        sa.Column("best_bid", sa.Float(), nullable=True),
        sa.Column("best_ask", sa.Float(), nullable=True),
        sa.Column("clear_book_on_start", sa.Boolean(), nullable=True),
        sa.Column("manual_activation", sa.Boolean(), nullable=True),
        sa.Column("neg_risk_other", sa.Boolean(), nullable=True),
        sa.Column("uma_resolution_statuses", sa.Text(), nullable=True),
        sa.Column("pending_deployment", sa.Boolean(), nullable=True),
        sa.Column("deploying", sa.Boolean(), nullable=True),
        sa.Column("deploying_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rfq_enabled", sa.Boolean(), nullable=True),
        sa.Column("holding_rewards_enabled", sa.Boolean(), nullable=True),
        sa.Column("fees_enabled", sa.Boolean(), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_market_gamma_metadata_group_slug", "market_gamma_metadata", ["group_slug"])

    op.create_table(
        "market_gamma_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("ticker", sa.String(length=128), nullable=True),
        sa.Column("slug", sa.String(length=256), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resolution_source", sa.String(length=512), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("image", sa.String(length=512), nullable=True),
        sa.Column("icon", sa.String(length=512), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=True),
        sa.Column("new", sa.Boolean(), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=True),
        sa.Column("restricted", sa.Boolean(), nullable=True),
        sa.Column("liquidity", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("open_interest", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("sort_by", sa.String(length=64), nullable=True),
        sa.Column("created_at_raw", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_raw", sa.DateTime(timezone=True), nullable=True),
        sa.Column("competitive", sa.Float(), nullable=True),
        sa.Column("volume_1wk", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume_1mo", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("volume_1yr", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("enable_order_book", sa.Boolean(), nullable=True),
        sa.Column("liquidity_clob", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("neg_risk", sa.Boolean(), nullable=True),
        sa.Column("neg_risk_market_id", sa.String(length=128), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("cyom", sa.Boolean(), nullable=True),
        sa.Column("show_all_outcomes", sa.Boolean(), nullable=True),
        sa.Column("show_market_images", sa.Boolean(), nullable=True),
        sa.Column("enable_neg_risk", sa.Boolean(), nullable=True),
        sa.Column("automatically_active", sa.Boolean(), nullable=True),
        sa.Column("neg_risk_augmented", sa.Boolean(), nullable=True),
        sa.Column("pending_deployment", sa.Boolean(), nullable=True),
        sa.Column("deploying", sa.Boolean(), nullable=True),
        sa.Column("deploying_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("competitive_flags", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_market_gamma_events_market_id", "market_gamma_events", ["market_id"])

    op.create_table(
        "resolutions",
        sa.Column("condition_id", sa.String(length=66), primary_key=True, nullable=False),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'conditional_tokens'"),
        ),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "event_id", sa.String(length=128), sa.ForeignKey("markets.event_id", ondelete="SET NULL"), nullable=True
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
        sa.Column("winning_outcome_id", sa.Integer(), nullable=True),
        sa.Column("rake_bps", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
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
    op.create_index("ix_resolutions_market_id", "resolutions", ["market_id"])
    op.create_index("ix_resolutions_event_id", "resolutions", ["event_id"])

    op.create_table(
        "factory_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("factory_address", sa.String(length=64), nullable=False),
        sa.Column(
            "market_address",
            sa.String(length=64),
            sa.ForeignKey("markets.market_address", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("factory_address", "event", "tx_hash", name="ux_factory_events_dedupe"),
    )
    op.create_index("ix_factory_events_factory", "factory_events", ["factory_address"])
    op.create_index("ix_factory_events_market", "factory_events", ["market_address"])
    op.create_index("ix_factory_events_tx_hash", "factory_events", ["tx_hash"])

    op.create_table(
        "quotes",
        sa.Column("quote_id", sa.String(length=66), primary_key=True, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="issued"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("stake_zen", sa.Numeric(precision=32, scale=8), nullable=False),
        sa.Column("stake_wei", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("fx_scaled", sa.BigInteger(), nullable=False),
        sa.Column("zen_usd", sa.Float(), nullable=False),
        sa.Column(
            "market_id",
            sa.String(length=128),
            sa.ForeignKey("markets.event_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("market_address", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("wallet_address", sa.String(length=64), nullable=True),
        sa.Column("outcome_id", sa.Integer(), nullable=True),
        sa.Column("chain_id", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('issued','consumed','expired')",
            name="ck_quotes_status",
        ),
    )
    op.create_index("ix_quotes_market_id", "quotes", ["market_id"])
    op.create_index("ix_quotes_user_id", "quotes", ["user_id"])
    op.create_index("ix_quotes_wallet_address", "quotes", ["wallet_address"])
    op.create_index("ix_quotes_status", "quotes", ["status"])
    if is_pg:
        op.create_index(
            "ix_quotes_expires_at_issued",
            "quotes",
            ["expires_at"],
            postgresql_where=sa.text("status = 'issued'"),
        )
    else:
        op.create_index("ix_quotes_expires_at", "quotes", ["expires_at"])

    # Commitments and settlement data for zk-proof generation
    op.create_table(
        "commitments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_address", sa.String(length=64), nullable=False),
        sa.Column("outcome_id", sa.Integer(), nullable=False),
        sa.Column("amount_wei", sa.BigInteger(), nullable=False),
        sa.Column("salt", sa.String(length=66), nullable=True),
        sa.Column("ticket_hash", sa.String(length=66), nullable=False),
        sa.Column("leaf", sa.String(length=66), nullable=False),
        sa.Column("leaf_index", sa.Integer(), nullable=True),
        sa.Column("tx_hash", sa.String(length=66), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_commitments_market_id", "commitments", ["market_id"])
    op.create_index("ix_commitments_market_user", "commitments", ["market_id", "user_address"])
    op.create_index("ix_commitments_user_address", "commitments", ["user_address"])
    op.create_index("ix_commitments_tx_hash", "commitments", ["tx_hash"])

    op.create_table(
        "commitment_merkle_paths",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "commitment_id",
            sa.BigInteger(),
            sa.ForeignKey("commitments.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column(
            "market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
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
        sa.Column("settlement_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_tx_hash", sa.String(length=66), nullable=True),
        sa.Column("settlement_block_number", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "proof_status IN ('none','requested','generated','failed')",
            name="ck_settlements_proof_status",
        ),
    )
    op.create_index("ix_settlements_market_id", "settlements", ["market_id"])
    op.create_index("ix_settlements_proof_status", "settlements", ["proof_status"])
    op.create_index("ix_settlements_tx_hash", "settlements", ["settlement_tx_hash"])

    # Hedger treasury snapshots (folded from former 0002 migration)
    hedger_table = "hedger_treasury_snapshots"
    hedger_idx = "ix_hedger_treasury_snapshots_market_id"
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if hedger_table not in existing_tables:
        op.create_table(
            hedger_table,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "market_id",
                sa.String(length=128),
                sa.ForeignKey("markets.event_id", ondelete="CASCADE"),
                nullable=False,
            ),
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
    if not any(idx.get("name") == hedger_idx for idx in sa.inspect(op.get_bind()).get_indexes(hedger_table)):
        op.create_index(
            hedger_idx,
            hedger_table,
            ["market_id"],
        )

    # Optional ledger/audit helpers for future features
    op.create_table(
        "chains",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("rpc_url", sa.String(length=512), nullable=False),
        sa.Column("explorer_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "wallet_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("preferred_chain_id", sa.BigInteger(), nullable=True),
        sa.Column("referral_code", sa.String(length=64), nullable=True),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("risk_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_wallet_sessions_wallet", "wallet_sessions", ["wallet_address"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_wallet", sa.String(length=64), nullable=True),
        sa.Column("actor_type", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("subject_type", sa.String(length=128), nullable=True),
        sa.Column("subject_id", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_subject", "audit_logs", ["subject_type", "subject_id"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("cursor", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ingestion_jobs_source_status", "ingestion_jobs", ["source", "status"])

    op.create_table(
        "webhooks_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("target_url", sa.String(length=512), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_webhooks_outbox_status", "webhooks_outbox", ["status"])
    op.create_index("ix_webhooks_status_next_retry", "webhooks_outbox", ["status", "next_retry_at"])

    op.create_table(
        "rate_limits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_request_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rate_limits_scope_key", "rate_limits", ["scope", "key"])

    op.create_table(
        "fx_prices",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_fx_prices_source_time", "fx_prices", ["source", "recorded_at"])

    op.create_table(
        "market_stats",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("volume_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("liquidity_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("open_interest_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("fees_collected_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("trades_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ux_market_stats_market_date", "market_stats", ["market_id", "as_of_date"], unique=True)

    op.create_table(
        "hedger_positions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("size_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("size_zen", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("fees_paid_usd", sa.Numeric(precision=32, scale=8), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_hedger_positions_market_outcome", "hedger_positions", ["market_id", "outcome_id"])
    op.create_index("ix_hedger_positions_state", "hedger_positions", ["state"])

    op.create_table(
        "proof_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("circuit_hash", sa.String(length=66), nullable=True),
        sa.Column("prover_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_proof_jobs_request_id", "proof_jobs", ["request_id"])
    op.create_index("ix_proof_jobs_status", "proof_jobs", ["status"])

    op.create_table(
        "settlement_receipts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "market_address",
            sa.String(length=64),
            sa.ForeignKey("markets.market_address", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("proof_hash", sa.String(length=66), nullable=True),
        sa.Column("proof", sa.Text(), nullable=True),
        sa.Column("public_signals", sa.JSON(), nullable=True),
        sa.Column("prover_version", sa.String(length=64), nullable=True),
        sa.Column("circuit_hash", sa.String(length=66), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("market_id", "request_id", name="ux_settlement_receipts_market_request"),
    )
    op.create_index("ix_settlement_receipts_market_id", "settlement_receipts", ["market_id"])
    op.create_index("ix_settlement_receipts_market_address", "settlement_receipts", ["market_address"])
    op.create_index("ix_settlement_receipts_request_id", "settlement_receipts", ["request_id"])

    op.create_table(
        "schema_versions",
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # DB-level updated_at maintenance for writes that bypass the ORM
    if is_pg:
        op.execute(
            """
            CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = timezone('utc', now());
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        tables_with_updated_at = [
            "markets",
            "resolutions",
            "quotes",
            "settlements",
            "proof_jobs",
            "settlement_receipts",
            "wallet_sessions",
            "ingestion_jobs",
            "webhooks_outbox",
            "rate_limits",
            "hedger_positions",
        ]
        for table in tables_with_updated_at:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION set_updated_at();
                """
            )


def downgrade() -> None:
    is_pg = _is_postgres()
    if is_pg:
        for table in [
            "markets",
            "resolutions",
            "quotes",
            "settlements",
            "proof_jobs",
            "settlement_receipts",
            "wallet_sessions",
            "ingestion_jobs",
            "webhooks_outbox",
            "rate_limits",
            "hedger_positions",
        ]:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
        op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.drop_table("schema_versions")
    op.drop_index("ix_settlement_receipts_request_id", table_name="settlement_receipts")
    op.drop_index("ix_settlement_receipts_market_address", table_name="settlement_receipts")
    op.drop_index("ix_settlement_receipts_market_id", table_name="settlement_receipts")
    op.drop_table("settlement_receipts")
    op.drop_index("ix_proof_jobs_status", table_name="proof_jobs")
    op.drop_index("ix_proof_jobs_request_id", table_name="proof_jobs")
    op.drop_table("proof_jobs")
    op.drop_index("ix_hedger_positions_state", table_name="hedger_positions")
    op.drop_index("ix_hedger_positions_market_outcome", table_name="hedger_positions")
    op.drop_table("hedger_positions")
    op.drop_index("ux_market_stats_market_date", table_name="market_stats")
    op.drop_table("market_stats")
    op.drop_index("ix_fx_prices_source_time", table_name="fx_prices")
    op.drop_table("fx_prices")
    op.drop_index("ix_rate_limits_scope_key", table_name="rate_limits")
    op.drop_table("rate_limits")
    op.drop_index("ix_webhooks_status_next_retry", table_name="webhooks_outbox")
    op.drop_index("ix_webhooks_outbox_status", table_name="webhooks_outbox")
    op.drop_table("webhooks_outbox")
    op.drop_index("ix_ingestion_jobs_source_status", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_audit_logs_subject", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_wallet_sessions_wallet", table_name="wallet_sessions")
    op.drop_table("wallet_sessions")
    op.drop_table("chains")
    op.drop_index("ix_hedger_treasury_snapshots_market_id", table_name="hedger_treasury_snapshots")
    op.drop_table("hedger_treasury_snapshots")
    op.drop_index("ix_settlements_tx_hash", table_name="settlements")
    op.drop_index("ix_settlements_proof_status", table_name="settlements")
    op.drop_index("ix_settlements_market_id", table_name="settlements")
    op.drop_table("settlements")
    op.drop_index("ix_commitment_merkle_paths_commitment_level", table_name="commitment_merkle_paths")
    op.drop_table("commitment_merkle_paths")
    op.drop_index("ix_commitments_tx_hash", table_name="commitments")
    op.drop_index("ix_commitments_market_user", table_name="commitments")
    op.drop_index("ix_commitments_user_address", table_name="commitments")
    op.drop_index("ix_commitments_market_id", table_name="commitments")
    op.drop_table("commitments")
    if is_pg:
        op.drop_index("ix_quotes_expires_at_issued", table_name="quotes")
    else:
        op.drop_index("ix_quotes_expires_at", table_name="quotes")
    op.drop_index("ix_quotes_status", table_name="quotes")
    op.drop_index("ix_quotes_wallet_address", table_name="quotes")
    op.drop_index("ix_quotes_user_id", table_name="quotes")
    op.drop_index("ix_quotes_market_id", table_name="quotes")
    op.drop_table("quotes")
    op.drop_index("ix_factory_events_tx_hash", table_name="factory_events")
    op.drop_index("ix_factory_events_market", table_name="factory_events")
    op.drop_index("ix_factory_events_factory", table_name="factory_events")
    op.drop_table("factory_events")
    op.drop_index("ix_resolutions_event_id", table_name="resolutions")
    op.drop_index("ix_resolutions_market_id", table_name="resolutions")
    op.drop_index("ix_resolutions_block_number", table_name="resolutions")
    op.drop_table("resolutions")
    op.drop_index("ix_market_gamma_events_market_id", table_name="market_gamma_events")
    op.drop_table("market_gamma_events")
    op.drop_table("market_gamma_metadata")
    op.drop_index("ix_market_outcomes_market_id", table_name="market_outcomes")
    op.drop_table("market_outcomes")
    op.drop_index("ix_market_clob_tokens_market_id", table_name="market_clob_tokens")
    op.drop_table("market_clob_tokens")
    if is_pg:
        op.drop_index("ix_market_tags_gin", table_name="market_tags")
    op.drop_index("ix_market_tags_market_id", table_name="market_tags")
    op.drop_table("market_tags")
    op.drop_index("ix_markets_resolution_status", table_name="markets")
    op.drop_index("ix_markets_event_id", table_name="markets")
    op.drop_index("ix_markets_event_resolved", table_name="markets")
    op.drop_index("ix_markets_resolved_at", table_name="markets")
    op.drop_index("ix_markets_condition_id", table_name="markets")
    op.drop_index("ix_markets_slug", table_name="markets")
    op.drop_index("ix_markets_status_category", table_name="markets")
    op.drop_table("markets")
