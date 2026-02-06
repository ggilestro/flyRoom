"""Add print jobs and print agents tables.

Revision ID: 005
Revises: 001
Create Date: 2026-02-05

Adds support for the label printing system:
- print_agents: Local print clients that poll for jobs
- print_jobs: Queued print jobs for stocks
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create print_agents and print_jobs tables."""

    # Print agents table
    op.create_table(
        "print_agents",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("api_key", sa.String(64), unique=True, nullable=False),
        sa.Column("printer_name", sa.String(100), nullable=True),
        sa.Column("label_format", sa.String(50), default="dymo_11352"),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_print_agents_tenant_id", "print_agents", ["tenant_id"])
    op.create_index("ix_print_agents_api_key", "print_agents", ["api_key"])

    # Print jobs table
    op.create_table(
        "print_jobs",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("agent_id", mysql.CHAR(36), nullable=True),
        sa.Column("created_by_id", mysql.CHAR(36), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "claimed",
                "printing",
                "completed",
                "failed",
                "cancelled",
                name="printjobstatus",
            ),
            default="pending",
        ),
        sa.Column("stock_ids", sa.JSON(), nullable=False),
        sa.Column("label_format", sa.String(50), default="dymo_11352"),
        sa.Column("copies", sa.Integer(), default=1),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["print_agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_print_jobs_tenant_id", "print_jobs", ["tenant_id"])
    op.create_index("ix_print_jobs_status", "print_jobs", ["status"])
    op.create_index("ix_print_jobs_agent_id", "print_jobs", ["agent_id"])


def downgrade() -> None:
    """Drop print_jobs and print_agents tables."""
    op.drop_table("print_jobs")
    op.drop_table("print_agents")
