#!/bin/sh
# Load the demo catalog after migrations, but only into a database with no stores yet.
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
export PGHOST="${DATABASE_HOST:-postgres}"
export PGPORT="${DATABASE_PORT:-5432}"
export PGUSER="${DATABASE_USER:-shopchat_owner}"
export PGPASSWORD="${DATABASE_PASSWORD:-shopchat_owner}"
export PGDATABASE="${DATABASE_NAME:-shopchat}"

stores="$(psql -Atc 'SELECT count(*) FROM shops')"
if [ "$stores" -gt 0 ]; then
  echo "Database already has $stores store(s). Skipping the seed."
  exit 0
fi

pg_restore --data-only --disable-triggers --no-owner --dbname="$PGDATABASE" "$DIR/shopchat_seed.dump"
echo "Seed loaded: $(psql -Atc 'SELECT count(*) FROM products') products," \
  "$(psql -Atc 'SELECT count(*) FROM product_chunks') chunks."
