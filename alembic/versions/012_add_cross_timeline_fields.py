"""Add timeline fields to crosses table.

Revision ID: 012
Revises: 011
Create Date: 2026-02-12

Adds:
- flip_days (Integer, nullable, default 5) — days after mating to flip vials
- virgin_collection_days (Integer, nullable, default 12) — days after mating to collect virgins
- target_genotype (Text, nullable) — desired offspring genotype
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add timeline fields to crosses table."""
    op.add_column(
        "crosses",
        sa.Column("flip_days", sa.Integer(), nullable=True, server_default="5"),
    )
    op.add_column(
        "crosses",
        sa.Column("virgin_collection_days", sa.Integer(), nullable=True, server_default="12"),
    )
    op.add_column(
        "crosses",
        sa.Column("target_genotype", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove timeline fields from crosses table."""
    op.drop_column("crosses", "target_genotype")
    op.drop_column("crosses", "virgin_collection_days")
    op.drop_column("crosses", "flip_days")
