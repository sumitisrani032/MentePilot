"""Initial schema with row-level security.

Revision ID: 0001
Revises:
"""

import os

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_ISOLATED_TABLES = (
    "catalog_profiles",
    "products",
    "variants",
    "product_chunks",
    "sync_jobs",
    "usage_events",
)

_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE shops (
    id uuid PRIMARY KEY,
    domain text NOT NULL UNIQUE,
    access_token_encrypted bytea,
    scopes text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'active',
    features jsonb NOT NULL DEFAULT '{}',
    installed_at timestamptz NOT NULL DEFAULT now(),
    uninstalled_at timestamptz
);

CREATE TABLE catalog_profiles (
    shop_id uuid PRIMARY KEY REFERENCES shops(id) ON DELETE CASCADE,
    profile jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id uuid PRIMARY KEY,
    shop_id uuid NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    source_id text NOT NULL,
    handle text NOT NULL,
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    vendor text NOT NULL DEFAULT '',
    product_type text NOT NULL DEFAULT '',
    category text NOT NULL DEFAULT '',
    tags text[] NOT NULL DEFAULT '{}',
    status text NOT NULL,
    image_urls text[] NOT NULL DEFAULT '{}',
    min_price numeric(12,2) NOT NULL,
    max_price numeric(12,2) NOT NULL,
    compare_at_price numeric(12,2),
    currency text NOT NULL,
    available boolean NOT NULL,
    facts jsonb NOT NULL DEFAULT '{}',
    content_hash text NOT NULL,
    source_updated_at timestamptz,
    UNIQUE (shop_id, source_id)
);
CREATE INDEX ix_products_shop_id ON products (shop_id);
CREATE INDEX ix_products_facts ON products USING gin (facts);

CREATE TABLE variants (
    id uuid PRIMARY KEY,
    shop_id uuid NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    source_id text NOT NULL,
    inventory_item_id text,
    title text NOT NULL DEFAULT '',
    options jsonb NOT NULL DEFAULT '{}',
    price numeric(12,2) NOT NULL,
    compare_at_price numeric(12,2),
    available boolean NOT NULL,
    UNIQUE (shop_id, source_id)
);
CREATE INDEX ix_variants_shop_id ON variants (shop_id);
CREATE INDEX ix_variants_product_id ON variants (product_id);
CREATE INDEX ix_variants_inventory_item_id ON variants (inventory_item_id);

CREATE TABLE product_chunks (
    id uuid PRIMARY KEY,
    shop_id uuid NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    kind text NOT NULL,
    text text NOT NULL,
    embedding vector(1536) NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX ix_product_chunks_shop_id ON product_chunks (shop_id);
CREATE INDEX ix_product_chunks_product_id ON product_chunks (product_id);
CREATE INDEX ix_product_chunks_embedding ON product_chunks
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ix_product_chunks_search_vector ON product_chunks USING gin (search_vector);

CREATE TABLE sync_jobs (
    id uuid PRIMARY KEY,
    shop_id uuid NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    type text NOT NULL,
    status text NOT NULL,
    processed integer NOT NULL DEFAULT 0,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_sync_jobs_shop_id ON sync_jobs (shop_id);

CREATE TABLE usage_events (
    id uuid PRIMARY KEY,
    shop_id uuid NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    kind text NOT NULL,
    quantity integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_usage_events_shop_id ON usage_events (shop_id);
"""


def upgrade() -> None:
    password = os.environ.get("SHOPCHAT_APP_PASSWORD", "shopchat_app").replace("'", "''")
    # asyncpg runs one statement per call.
    for statement in filter(str.strip, _SCHEMA.split(";")):
        op.execute(statement)
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'shopchat_app') THEN
                CREATE ROLE shopchat_app LOGIN PASSWORD '{password}'
                    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END $$
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO shopchat_app"
    )
    op.execute("REVOKE ALL ON alembic_version FROM shopchat_app")
    for table in _ISOLATED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY shop_isolation ON {table}
            USING (shop_id = NULLIF(current_setting('app.shop_id', true), '')::uuid)
            WITH CHECK (shop_id = NULLIF(current_setting('app.shop_id', true), '')::uuid)
            """
        )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE usage_events, sync_jobs, product_chunks, variants, products,
            catalog_profiles, shops
        """
    )
