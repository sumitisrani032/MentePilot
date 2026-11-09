"""Record when each product was last indexed.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN indexed_at timestamptz")
    op.execute("CREATE INDEX ix_products_indexed_at ON products (indexed_at)")
    # Products indexed before this column existed get the migration time.
    op.execute(
        "UPDATE products SET indexed_at = now() "
        "WHERE id IN (SELECT DISTINCT product_id FROM product_chunks)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_products_indexed_at")
    op.execute("ALTER TABLE products DROP COLUMN indexed_at")
