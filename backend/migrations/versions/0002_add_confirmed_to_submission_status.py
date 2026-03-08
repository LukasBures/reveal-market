"""add confirmed to submission_status check constraint

Revision ID: 0002_add_confirmed
Revises: 0001_baseline
Create Date: 2026-03-08 00:00:00.000000

The baseline migration omitted 'confirmed' from the settlements
submission_status check constraint, preventing the worker from
recording the terminal success state after on-chain settlement.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_add_confirmed"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_settlements_submission_status", "settlements", type_="check")
    op.create_check_constraint(
        "ck_settlements_submission_status",
        "settlements",
        "submission_status IN ('none','queued','processing','submitted','confirmed','failed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_settlements_submission_status", "settlements", type_="check")
    op.create_check_constraint(
        "ck_settlements_submission_status",
        "settlements",
        "submission_status IN ('none','queued','processing','submitted','failed')",
    )
