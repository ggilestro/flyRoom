"""Add collaborators and stock_shares tables.

Revision ID: 016
Revises: 015
Create Date: 2026-02-18

Adds:
- collaborators table: tenant-to-tenant directional relationship
- stock_shares table: per-stock sharing with collaborator tenants
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import CHAR

# revision identifiers
revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Collaborators table
    op.create_table(
        "collaborators",
        sa.Column("id", CHAR(36), primary_key=True),
        sa.Column(
            "tenant_id",
            CHAR(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collaborator_id",
            CHAR(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column(
            "created_by_id",
            CHAR(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("tenant_id", "collaborator_id", name="uq_collaborator_pair"),
    )
    op.create_index("ix_collaborators_tenant_id", "collaborators", ["tenant_id"])
    op.create_index("ix_collaborators_collaborator_id", "collaborators", ["collaborator_id"])

    # Stock shares table
    op.create_table(
        "stock_shares",
        sa.Column(
            "stock_id",
            CHAR(36),
            sa.ForeignKey("stocks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "shared_with_tenant_id",
            CHAR(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column(
            "shared_by_id",
            CHAR(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_stock_shares_shared_with_tenant_id", "stock_shares", ["shared_with_tenant_id"]
    )


def downgrade() -> None:
    op.drop_table("stock_shares")
    op.drop_table("collaborators")
