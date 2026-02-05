"""Initial database schema.

Revision ID: 001
Revises:
Create Date: 2026-02-02

Complete schema for FlyStocks application including:
- Tenants (labs) and Organizations
- Users with email verification
- Stocks with origin tracking (repositories, internal, external)
- Trays for physical location
- Tags and Stock-Tags
- Crosses
- Stock requests for inter-lab sharing
- External references
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables."""

    # Organizations table (parent entity for labs)
    op.create_table(
        "organizations",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("website", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Tenants table (labs)
    op.create_table(
        "tenants",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("organization_id", mysql.CHAR(36), nullable=True),
        sa.Column("is_org_admin", sa.Boolean(), default=False, server_default="0"),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("invitation_token", sa.String(64), nullable=True),
        sa.Column("invitation_token_created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.UniqueConstraint("invitation_token"),
    )
    op.create_index("ix_tenants_organization_id", "tenants", ["organization_id"])

    # Users table
    op.create_table(
        "users",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("admin", "user", name="userrole"), nullable=True),
        sa.Column(
            "status", sa.Enum("pending", "approved", "rejected", name="userstatus"), nullable=True
        ),
        sa.Column("is_active", sa.Boolean(), nullable=True, default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        # Password reset
        sa.Column("password_reset_token", sa.String(64), unique=True, nullable=True),
        sa.Column("password_reset_token_expires", sa.DateTime(), nullable=True),
        # Email verification
        sa.Column("is_email_verified", sa.Boolean(), default=False, server_default="0"),
        sa.Column("email_verification_token", sa.String(64), unique=True, nullable=True),
        sa.Column("email_verification_sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index(
        "ix_users_email_verification_token", "users", ["email_verification_token"], unique=True
    )

    # Organization join requests
    op.create_table(
        "organization_join_requests",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("organization_id", mysql.CHAR(36), nullable=False),
        sa.Column("tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("requested_by_id", mysql.CHAR(36), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="orgjoinrequeststatus"),
            default="pending",
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("responded_by_id", mysql.CHAR(36), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["responded_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_org_join_requests_org_id", "organization_join_requests", ["organization_id"]
    )
    op.create_index("ix_org_join_requests_tenant_id", "organization_join_requests", ["tenant_id"])

    # Trays table (physical location)
    op.create_table(
        "trays",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "tray_type", sa.Enum("numeric", "grid", "custom", name="traytype"), default="numeric"
        ),
        sa.Column("max_positions", sa.Integer(), default=100),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("cols", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tray_tenant_name"),
    )
    op.create_index("ix_trays_tenant_id", "trays", ["tenant_id"])

    # Tags table
    op.create_table(
        "tags",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("color", sa.String(7), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tag_tenant_name"),
    )
    op.create_index("ix_tags_tenant_id", "tags", ["tenant_id"])

    # Stocks table
    op.create_table(
        "stocks",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("stock_id", sa.String(100), nullable=False),
        sa.Column("genotype", sa.Text(), nullable=False),
        # Origin/Source tracking
        sa.Column(
            "origin",
            sa.Enum("repository", "internal", "external", name="stockorigin"),
            default="internal",
            server_default="internal",
        ),
        sa.Column(
            "repository",
            sa.Enum(
                "bdsc",
                "vdrc",
                "kyoto",
                "nig",
                "dgrc",
                "flyorf",
                "trip",
                "exelixis",
                "other",
                name="stockrepository",
            ),
            nullable=True,
        ),
        sa.Column("repository_stock_id", sa.String(50), nullable=True),
        sa.Column("external_source", sa.String(255), nullable=True),
        sa.Column("original_genotype", sa.Text(), nullable=True),
        # Physical location
        sa.Column("tray_id", mysql.CHAR(36), nullable=True),
        sa.Column("position", sa.String(20), nullable=True),
        # Ownership and visibility
        sa.Column("owner_id", mysql.CHAR(36), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum("lab_only", "organization", "public", name="stockvisibility"),
            default="lab_only",
            server_default="lab_only",
        ),
        sa.Column("hide_from_org", sa.Boolean(), default=False, server_default="0"),
        # Metadata
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_by_id", mysql.CHAR(36), nullable=True),
        sa.Column(
            "modified_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()
        ),
        sa.Column("modified_by_id", mysql.CHAR(36), nullable=True),
        sa.Column("external_metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tray_id"], ["trays.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["modified_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "stock_id", name="uq_stock_tenant_stock_id"),
    )
    op.create_index("ix_stocks_tenant_id", "stocks", ["tenant_id"])
    op.create_index("ix_stocks_genotype", "stocks", ["genotype"], mysql_length=100)
    op.create_index("ix_stocks_origin", "stocks", ["origin"])
    op.create_index("ix_stocks_repository", "stocks", ["repository"])
    op.create_index("ix_stocks_visibility", "stocks", ["visibility"])
    op.create_index("ix_stocks_tray_id", "stocks", ["tray_id"])

    # Stock-Tags association table
    op.create_table(
        "stock_tags",
        sa.Column("stock_id", mysql.CHAR(36), nullable=False),
        sa.Column("tag_id", mysql.CHAR(36), nullable=False),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("stock_id", "tag_id"),
    )

    # Crosses table
    op.create_table(
        "crosses",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("parent_female_id", mysql.CHAR(36), nullable=False),
        sa.Column("parent_male_id", mysql.CHAR(36), nullable=False),
        sa.Column("offspring_id", mysql.CHAR(36), nullable=True),
        sa.Column("planned_date", sa.DateTime(), nullable=True),
        sa.Column("executed_date", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("planned", "in_progress", "completed", "failed", name="crossstatus"),
            nullable=True,
        ),
        sa.Column("expected_outcomes", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_by_id", mysql.CHAR(36), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_female_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_male_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["offspring_id"], ["stocks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crosses_tenant_id", "crosses", ["tenant_id"])

    # External references table
    op.create_table(
        "external_references",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("stock_id", mysql.CHAR(36), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_id", "source", name="uq_extref_stock_source"),
    )

    # Stock requests table (inter-lab sharing)
    op.create_table(
        "stock_requests",
        sa.Column("id", mysql.CHAR(36), primary_key=True),
        sa.Column("stock_id", mysql.CHAR(36), nullable=False),
        sa.Column("requester_user_id", mysql.CHAR(36), nullable=True),
        sa.Column("requester_tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("owner_tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "fulfilled",
                "cancelled",
                name="stockrequeststatus",
            ),
            default="pending",
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("response_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()
        ),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("responded_by_id", mysql.CHAR(36), nullable=True),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requester_tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["responded_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_stock_requests_stock_id", "stock_requests", ["stock_id"])
    op.create_index(
        "ix_stock_requests_requester_tenant_id", "stock_requests", ["requester_tenant_id"]
    )
    op.create_index("ix_stock_requests_owner_tenant_id", "stock_requests", ["owner_tenant_id"])
    op.create_index("ix_stock_requests_status", "stock_requests", ["status"])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("stock_requests")
    op.drop_table("external_references")
    op.drop_table("crosses")
    op.drop_table("stock_tags")
    op.drop_table("stocks")
    op.drop_table("tags")
    op.drop_table("trays")
    op.drop_table("organization_join_requests")
    op.drop_table("users")
    op.drop_table("tenants")
    op.drop_table("organizations")
