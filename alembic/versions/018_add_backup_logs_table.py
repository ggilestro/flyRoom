"""Add backup_logs table.

Revision ID: 018
Revises: 017
Create Date: 2026-02-19

Stores backup run history (success/failure, size, duration) for the
automated daily database backup feature.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_logs",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("duration_seconds", sa.Float, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("backup_logs")
