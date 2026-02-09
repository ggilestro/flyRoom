"""Add invitations table for email-based user invitations.

Revision ID: 010
Revises: 009
Create Date: 2026-02-09

Adds:
- invitations table with email, type, token, status, expiry
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create invitations table."""
    op.create_table(
        "invitations",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.CHAR(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invited_by_id",
            sa.CHAR(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "invitation_type",
            sa.Enum("lab_member", "new_tenant", name="invitationtype"),
            nullable=False,
        ),
        sa.Column("token", sa.String(64), unique=True, nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "accepted", "cancelled", "expired", name="invitationstatus"),
            default="pending",
        ),
        sa.Column(
            "organization_id",
            sa.CHAR(36),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("accepted_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_invitations_tenant_id", "invitations", ["tenant_id"])
    op.create_index("ix_invitations_token", "invitations", ["token"])
    op.create_index("ix_invitations_email", "invitations", ["email"])


def downgrade() -> None:
    """Drop invitations table."""
    op.drop_index("ix_invitations_email", table_name="invitations")
    op.drop_index("ix_invitations_token", table_name="invitations")
    op.drop_index("ix_invitations_tenant_id", table_name="invitations")
    op.drop_table("invitations")
