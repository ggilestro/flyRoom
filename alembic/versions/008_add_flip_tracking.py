"""Add flip tracking system.

Revision ID: 008
Revises: 007
Create Date: 2026-02-06

Adds:
- flip_events table for tracking stock flips
- flip settings columns to tenants table (warning/critical days, reminder enabled)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add flip tracking tables and columns."""
    # Create flip_events table
    op.create_table(
        "flip_events",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column(
            "stock_id",
            sa.CHAR(36),
            sa.ForeignKey("stocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "flipped_by_id",
            sa.CHAR(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "flipped_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create indexes
    op.create_index("ix_flip_events_stock_id", "flip_events", ["stock_id"])
    op.create_index("ix_flip_events_flipped_at", "flip_events", ["flipped_at"])

    # Add flip settings columns to tenants
    op.add_column(
        "tenants",
        sa.Column(
            "flip_warning_days",
            sa.Integer(),
            nullable=False,
            server_default="21",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "flip_critical_days",
            sa.Integer(),
            nullable=False,
            server_default="31",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "flip_reminder_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    """Remove flip tracking tables and columns."""
    # Remove tenant columns
    op.drop_column("tenants", "flip_reminder_enabled")
    op.drop_column("tenants", "flip_critical_days")
    op.drop_column("tenants", "flip_warning_days")

    # Drop indexes and table
    op.drop_index("ix_flip_events_flipped_at", "flip_events")
    op.drop_index("ix_flip_events_stock_id", "flip_events")
    op.drop_table("flip_events")
