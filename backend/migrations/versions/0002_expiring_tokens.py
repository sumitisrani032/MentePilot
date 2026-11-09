"""Store expiring Shopify offline tokens.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE shops ADD COLUMN refresh_token_encrypted bytea")
    op.execute("ALTER TABLE shops ADD COLUMN access_token_expires_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE shops DROP COLUMN access_token_expires_at")
    op.execute("ALTER TABLE shops DROP COLUMN refresh_token_encrypted")
