"""Add code_type column to print_jobs table.

Revision ID: 006
Revises: 005
Create Date: 2026-02-05

Adds code_type column to support QR codes vs barcodes on labels.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add code_type column to print_jobs table."""
    op.add_column(
        "print_jobs",
        sa.Column("code_type", sa.String(20), nullable=False, server_default="qr"),
    )


def downgrade() -> None:
    """Remove code_type column from print_jobs table."""
    op.drop_column("print_jobs", "code_type")
