"""extend settlement status

Revision ID: 0003_extend_settlement_status
Revises: 0002_add_commitment_payout
Create Date: 2026-01-14T18:40:00Z

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_extend_settlement_status"
down_revision = "0002_add_commitment_payout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE settlements DROP CONSTRAINT IF EXISTS ck_settlements_proof_status")
    op.execute(
        "ALTER TABLE settlements ADD CONSTRAINT ck_settlements_proof_status "
        "CHECK (proof_status IN ('none','pending','generating','requested','generated','failed'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE settlements DROP CONSTRAINT IF EXISTS ck_settlements_proof_status")
    op.execute(
        "ALTER TABLE settlements ADD CONSTRAINT ck_settlements_proof_status "
        "CHECK (proof_status IN ('none','requested','generated','failed'))"
    )
