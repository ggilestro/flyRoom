"""Add tenant label settings fields.

Revision ID: 007
Revises: 006
Create Date: 2026-02-05

Adds default label settings to tenants table:
- default_label_format: Label format (e.g., dymo_11352)
- default_code_type: QR or barcode
- default_copies: Copies per label
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add label settings columns to tenants table."""
    op.add_column(
        "tenants",
        sa.Column(
            "default_label_format",
            sa.String(50),
            nullable=False,
            server_default="dymo_11352",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "default_code_type",
            sa.String(20),
            nullable=False,
            server_default="qr",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "default_copies",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    """Remove label settings columns from tenants table."""
    op.drop_column("tenants", "default_copies")
    op.drop_column("tenants", "default_code_type")
    op.drop_column("tenants", "default_label_format")
