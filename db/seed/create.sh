#!/usr/bin/env bash
# Build db/seed/shopchat_seed.dump from a scrubbed copy. The working database is not changed.
set -euo pipefail

cd "$(dirname "$0")/../.."
SEED_SHOP="${SEED_SHOP:-cosmo-genie.myshopify.com}"
OUTPUT="db/seed/shopchat_seed.dump"
owner=(-U shopchat_owner)

run() { docker compose exec -T postgres "$@"; }

run psql "${owner[@]}" -d postgres -v ON_ERROR_STOP=1 -q <<SQL
DROP DATABASE IF EXISTS shopchat_seed;
CREATE DATABASE shopchat_seed;
SQL

run sh -c "pg_dump -U shopchat_owner shopchat | psql -U shopchat_owner -d shopchat_seed -q -v ON_ERROR_STOP=1" >/dev/null

run psql "${owner[@]}" -d shopchat_seed -v ON_ERROR_STOP=1 -q <<SQL
BEGIN;
DELETE FROM shops WHERE domain <> '${SEED_SHOP}';
UPDATE shops SET access_token_encrypted = NULL, refresh_token_encrypted = NULL,
                 access_token_expires_at = NULL, scopes = '';
DELETE FROM sync_jobs;
DELETE FROM usage_events;
COMMIT;
SQL

run pg_dump "${owner[@]}" -d shopchat_seed --format=custom --compress=9 --data-only \
  --exclude-table=alembic_version >"${OUTPUT}"

run psql "${owner[@]}" -d postgres -v ON_ERROR_STOP=1 -q -c "DROP DATABASE shopchat_seed;"
ls -lh "${OUTPUT}"
