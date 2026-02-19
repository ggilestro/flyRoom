"""Add lab_manager to user role enum.

Revision ID: 019
Revises: 018
Create Date: 2026-02-19

Adds 'lab_manager' value to the role ENUM column on the users table
so labs can designate a manager with admin-level permissions.
"""

from alembic import op

# revision identifiers
revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users MODIFY COLUMN role " "ENUM('admin', 'lab_manager', 'user') NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE users MODIFY COLUMN role " "ENUM('admin', 'user') NULL")
