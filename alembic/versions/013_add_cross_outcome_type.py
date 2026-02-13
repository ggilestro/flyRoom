"""Add cross outcome type and stock placeholder flag.

Revision ID: 013
Revises: 012
Create Date: 2026-02-13

Adds:
- outcome_type enum column to crosses (ephemeral, intermediate, new_stock)
- is_placeholder boolean to stocks (default False)
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add outcome_type to crosses and is_placeholder to stocks."""
    op.add_column(
        "crosses",
        sa.Column(
            "outcome_type",
            sa.Enum("ephemeral", "intermediate", "new_stock", name="crossoutcometype"),
            nullable=True,
            server_default="ephemeral",
        ),
    )
    op.add_column(
        "stocks",
        sa.Column("is_placeholder", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Remove outcome_type from crosses and is_placeholder from stocks."""
    op.drop_column("stocks", "is_placeholder")
    op.drop_column("crosses", "outcome_type")
