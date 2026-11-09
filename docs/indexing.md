# Catalog indexing

Every product, from any source, goes through `run_catalog_pipeline` in
`backend/src/shopchat/catalog/pipeline.py`.

```mermaid
flowchart TD
    A[Shopify import or webhook] --> N[NormalizedProduct]
    CSV[CSV import] --> N
    N --> H{Content hash changed?}
    H -- No --> SKIP[Skip, no cost]
    H -- Yes --> REC[Save a record first]
    REC --> F{{Parse stated facts<br/>gpt-4o-mini, batches of 50}}
    F --> E{{Add inferred facts<br/>only to sparse products}}
    E --> CH[Build chunks<br/>summary plus long attributes]
    CH --> EM[Embed<br/>text-embedding-3-small]
    EM --> DB[(products, variants,<br/>product_chunks, indexed_at)]
    DB --> P{{Rebuild store profile<br/>gpt-4o-mini}}
```

Progress is saved every 100 products, so a retry resumes instead of paying twice.

## First install

```mermaid
sequenceDiagram
    autonumber
    participant S as Shopify
    participant A as FastAPI
    participant Q as Redis queue
    participant W as Worker
    participant O as OpenAI
    participant D as Postgres
    S->>A: GET /auth/callback
    A->>S: Exchange code for expiring offline token
    A->>D: Save encrypted tokens
    A->>Q: enqueue sync_shop
    Q->>W: sync_shop
    W->>S: Start a bulk export
    alt Bulk operations allowed
        S-->>A: Webhook bulk_operations/finish
        A->>Q: enqueue finish_bulk
        Q->>W: finish_bulk
        W->>S: Download the export
    else Bulk denied
        W->>S: Read products page by page
    end
    W->>O: Facts, inferred facts, embeddings, profile
    W->>D: Save the index
```

## Keeping the index current

| Webhook | Job | Effect |
| --- | --- | --- |
| `products/create`, `products/update` | `upsert_product` | Re-index if the content hash changed |
| `products/delete` | `delete_product` | Remove the product and its chunks |
| `inventory_levels/update` | `update_inventory` | Update availability without a model call |
| `bulk_operations/finish` | `finish_bulk` | Index the finished export |
| `app/uninstalled` | `deactivate_shop` | Mark the store inactive |
| `shop/redact` | `redact_shop` | Delete the store's data |
| `customers/data_request`, `customers/redact` | none | Acknowledged; no customer data is stored |

Jobs retry up to 5 times with backoff. Webhooks are verified by HMAC before anything is queued.

## Facts

A fact has a value, a provenance and an optional caveat.

```json
{ "waterproof": { "value": true, "provenance": "stated", "caveat": null } }
```

- Only `stated` yes/no and number facts can be strict filters.
- A negation guard stops text like "not waterproof" from becoming `true`.
- Inferred facts are shown as "likely" and are never used as strict filters.
