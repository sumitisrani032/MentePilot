# Database

Postgres 16 with the pgvector extension. Migrations are in `backend/migrations`.

```mermaid
erDiagram
    shops ||--o| catalog_profiles : has
    shops ||--o{ products : sells
    shops ||--o{ sync_jobs : runs
    shops ||--o{ usage_events : records
    products ||--o{ variants : has
    products ||--o{ product_chunks : "indexed as"

    shops {
        uuid id PK
        text domain UK
        bytea access_token_encrypted
        bytea refresh_token_encrypted
        timestamptz access_token_expires_at
        text scopes
        text status
        jsonb features
        timestamptz installed_at
        timestamptz uninstalled_at
    }
    catalog_profiles {
        uuid shop_id PK
        jsonb profile
        timestamptz updated_at
    }
    products {
        uuid id PK
        uuid shop_id FK
        text source_id
        text handle
        text title
        text description
        text vendor
        text product_type
        text category
        text_array tags
        text status
        text_array image_urls
        numeric min_price
        numeric max_price
        numeric compare_at_price
        text currency
        boolean available
        jsonb facts
        text content_hash
        timestamptz source_updated_at
        timestamptz indexed_at
    }
    variants {
        uuid id PK
        uuid shop_id FK
        uuid product_id FK
        text source_id
        text inventory_item_id
        text title
        jsonb options
        numeric price
        numeric compare_at_price
        boolean available
    }
    product_chunks {
        uuid id PK
        uuid shop_id FK
        uuid product_id FK
        text kind
        text text
        vector embedding
        tsvector search_vector
    }
    sync_jobs {
        uuid id PK
        uuid shop_id FK
        text type
        text status
        int processed
        text error
    }
    usage_events {
        uuid id PK
        uuid shop_id FK
        text kind
        int quantity
    }
```

## Store isolation

| Role | Used by | Rights |
| --- | --- | --- |
| `shopchat_owner` | Migrations and seeding | Owns the schema |
| `shopchat_app` | API and worker | Data access only, cannot bypass row-level security |

Every table except `shops` has the `shop_isolation` policy, with `FORCE ROW LEVEL SECURITY`:

```sql
USING (shop_id = NULLIF(current_setting('app.shop_id', true), '')::uuid)
```

`session_for_shop(shop_id)` sets `app.shop_id` for one transaction. A query with no store context
returns no rows, so a forgotten filter cannot leak another store's data.

## Redis

| Key | Holds | Lifetime |
| --- | --- | --- |
| `chat:{shop_id}:{session_id}` | Last 10 turns | 24 hours |
| arq keys | Background jobs | Managed by arq |

## Migrations

| Revision | Change |
| --- | --- |
| `0001_initial` | Schema, roles, row-level security, HNSW and full-text indexes |
| `0002_expiring_tokens` | Refresh token and expiry for Shopify expiring tokens |
| `0003_product_indexed_at` | When each product was last indexed |
