# Seed data

`db/seed/shopchat_seed.dump` lets you start with a fully indexed catalog, without paying to embed
it again.

| Included | Removed |
| --- | --- |
| The demo store `cosmo-genie.myshopify.com` | Encrypted Shopify access and refresh tokens |
| Its products, variants and store profile | Sync history and usage events |
| Its RAG chunks and embeddings | Evaluation and test stores |

## Loading it

Docker Compose runs migrations and then loads the seed automatically, if the database is empty.

```bash
docker compose up -d --build
```

To load it into a Postgres you run yourself, after running migrations:

```bash
cd backend && uv run alembic upgrade head && cd ..
DATABASE_HOST=localhost DATABASE_PORT=5432 ./db/seed/restore.sh
```

The script skips loading if the database already contains stores. It connects as `shopchat_owner`,
a superuser in the Compose database, because seeding must bypass row-level security.

## Try it

The demo store has no Shopify token, so the widget cannot connect to it. Use the command line:

```bash
docker compose run --rm -e LLM_CALLS_ENABLED=true api \
  uv run --no-sync python scripts/ask.py "I'm going to the beach"
```

This needs `OPENAI_API_KEY` in `backend/.env`. Each question costs a fraction of a cent.

To confirm the data loaded, with no OpenAI call:

```bash
docker compose exec postgres psql -U shopchat_owner -d shopchat \
  -c "select count(*) from products" -c "select count(*) from product_chunks"
```

## Regenerating it

```bash
./db/seed/create.sh
```

The script copies the database, removes everything in the table above from the copy, and dumps the
data. Your database is not changed.

Embeddings were made with `text-embedding-3-small`. If you change that model, re-index, because
vectors from different models cannot be compared.
