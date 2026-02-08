"""Add agent config and pairing support.

Revision ID: 009
Revises: 008
Create Date: 2026-02-07

Adds:
- default_orientation to tenants table
- poll_interval, log_level, available_printers, config_version to print_agents table
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add agent config columns."""
    # Tenant: add default_orientation
    op.add_column(
        "tenants",
        sa.Column(
            "default_orientation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # PrintAgent: add config fields
    op.add_column(
        "print_agents",
        sa.Column(
            "poll_interval",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
    )
    op.add_column(
        "print_agents",
        sa.Column(
            "log_level",
            sa.String(10),
            nullable=False,
            server_default="INFO",
        ),
    )
    op.add_column(
        "print_agents",
        sa.Column(
            "available_printers",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column(
        "print_agents",
        sa.Column(
            "config_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    """Remove agent config columns."""
    op.drop_column("print_agents", "config_version")
    op.drop_column("print_agents", "available_printers")
    op.drop_column("print_agents", "log_level")
    op.drop_column("print_agents", "poll_interval")
    op.drop_column("tenants", "default_orientation")
