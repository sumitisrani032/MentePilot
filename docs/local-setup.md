# Local setup, step by step

Run the chatbot on your own computer with no Shopify store. The database comes from the seed dump,
which already holds 1,000 indexed products, so setup needs no OpenAI calls. Only asking the chatbot
a question costs money.

Run every command from the repository root unless a step says `cd backend` or `cd frontend`.

## 1. Install the tools

| Tool | Needed for |
| --- | --- |
| Git | Getting the code |
| Docker with Compose | Postgres, Redis and, optionally, the whole app |
| Python 3.12 and [uv](https://docs.astral.sh/uv/) | Running the backend outside Docker (step 7) |
| Node.js 20 or later | Widget tests only |

Install Docker on Ubuntu:

```bash
curl -fsSL https://get.docker.com | sudo sh   # Install Docker Engine and the Compose plugin
sudo usermod -aG docker "$USER"               # Let your user run docker without sudo
newgrp docker                                 # Apply the group now, or log out and in
```

On macOS or Windows, install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
instead and start it.

Check the installs:

```bash
docker --version           # Docker is installed
docker compose version     # The Compose plugin is installed
docker ps                  # The Docker service is running (an empty list is fine)
uv --version               # Only for step 7
```

Install uv if needed: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## 2. Get the code

```bash
git clone https://github.com/sumitisrani032/MentePilot.git   # First time only
cd MentePilot
git checkout develop                                          # The working branch
git pull                                                      # Later: fetch the latest changes
```

## 3. Create the settings file

```bash
cp backend/.env.example backend/.env                          # Your local settings, never committed
python3 -c "import secrets; print(secrets.token_urlsafe(48))" # Prints a random secret
```

Open `backend/.env` and set:

| Setting | Value |
| --- | --- |
| `WIDGET_TOKEN_SECRET` | The secret printed above (the chat cannot start without it) |
| `OPENAI_API_KEY` | Your OpenAI key, needed only to get answers |

Leave the Shopify settings empty. They are not needed without a store.

## 4. Start everything in development mode with Docker

One command builds the image, starts Postgres and Redis, runs the migrations, loads the seed and
starts the API with the `/dev` page on:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

That start makes no OpenAI calls, so the chatbot opens but cannot answer. To get answers (paid
calls), put `LLM_CALLS_ENABLED=true` in front:

```bash
LLM_CALLS_ENABLED=true docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Check it:

```bash
docker ps                         # Lists the running containers
docker compose ps -a              # api, worker, postgres, redis running; migrate and seed "Exited (0)"
docker compose logs seed          # Shows "Seed loaded: 1000 products, 4174 chunks."
curl http://localhost:8000/healthz   # Prints {"status":"ok"}
```

The seed only loads into an empty database. Later starts print "Skipping the seed".

`docker-compose.dev.yml` is for development only. It turns on `DEV_MODE`, and it mounts
`backend/src` and the widget files into the container. Python edits restart the server by
themselves, and widget edits show on a browser refresh. Plain `docker compose up -d` starts without
development mode, as for production.

## 5. Open the chatbot

Open <http://localhost:8000/dev> in your browser. Use the maximize button in the chat header to
make the chat fill the window.

After changing `backend/.env`, or to switch OpenAI calls on or off, run the step 4 command again.
Compose recreates only what changed.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f api   # Follow the API log
```

## 6. Check the data

```bash
docker compose exec postgres psql -U shopchat_owner -d shopchat \
  -c "select count(*) from products" -c "select count(*) from product_chunks"
```

Expect 1000 products and 4174 chunks.

## 7. Run the backend outside Docker (optional)

Step 4 is enough for most work. Use this to run the server with your own Python tools, such as a
debugger. Keep Postgres and Redis in Docker.

```bash
docker compose stop api worker    # Free port 8000 if the Docker API is running
docker compose up -d postgres redis
cd backend
uv sync                           # Install Python dependencies
uv run alembic upgrade head       # Create or update the tables
cd ..
docker compose run --rm --no-deps seed    # Load the seed if the database is still empty
cd backend
DEV_MODE=true LLM_CALLS_ENABLED=true uv run uvicorn shopchat.api.app:app --reload --port 8000
```

Open <http://localhost:8000/dev>. Use `LLM_CALLS_ENABLED=false` to open the page with no OpenAI
calls; the chatbot then cannot answer.

The worker is only needed for re-indexing. Start it in a second terminal:

```bash
cd backend
uv run arq shopchat.worker.main.WorkerSettings
```

## 8. Take a dump of your database

To save the seed for others (scrubbed: no tokens, no sync history, only the demo store):

```bash
./db/seed/create.sh               # Writes db/seed/shopchat_seed.dump; your database is not changed
git add db/seed/shopchat_seed.dump
git commit -m "chore(seed): refresh the seed dump"
```

`SEED_SHOP=your-store.myshopify.com ./db/seed/create.sh` keeps a different store.

For a full private backup (it includes encrypted tokens, so do not share it):

```bash
docker compose exec -T postgres pg_dump -U shopchat_owner -Fc shopchat > shopchat_backup.dump
```

## 9. Restore a dump

The seed, into an empty database:

```bash
docker compose run --rm --no-deps seed
```

To replace your database with a full backup from step 8:

```bash
docker compose exec -T postgres pg_restore -U shopchat_owner -d shopchat --clean --if-exists \
  < shopchat_backup.dump
```

To start again from the seed, delete the database volume. This erases all local data:

```bash
docker compose down -v            # Stop everything and delete the database
docker compose up -d              # Recreate it, migrate and load the seed again
```

## 10. Run the tests

The tests make no OpenAI calls.

```bash
cd backend
uv run pytest                     # Backend tests; Postgres and Redis must be running
uv run ruff check . && uv run mypy src
cd ../frontend
npm ci                            # Install Node dependencies, first time only
npm test && npm run lint          # Widget tests and lint
```

If Postgres or Redis use other ports, set them first, for example
`export SHOPCHAT_POSTGRES_PORT=55432 SHOPCHAT_REDIS_PORT=56379`.

## 11. Stop

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml stop   # Stop the containers and keep the data
docker compose down               # Remove the containers and keep the data
docker ps                         # Confirm nothing is still running
```

Press `Ctrl+C` to stop a server you started with `uv run`.

## Problems

| Problem | Fix |
| --- | --- |
| `port is already allocated` or `address already in use` | Set `SHOPCHAT_API_PORT`, `SHOPCHAT_POSTGRES_PORT` or `SHOPCHAT_REDIS_PORT` before `docker compose up`, for example `SHOPCHAT_POSTGRES_PORT=55432`. When running outside Docker, use the same port in `DATABASE_URL` and `DATABASE_OWNER_URL` in `backend/.env`. |
| `/dev` shows `{"detail":"Not Found"}` | Start with `docker-compose.dev.yml` (step 4), or `DEV_MODE=true` outside Docker. It never works through ngrok, only on your own computer. |
| The chat says the store is not in the database | The seed did not load. Run `docker compose logs seed`, then step 9. |
| The chat opens but never answers | Start with `LLM_CALLS_ENABLED=true` (step 4) and set `OPENAI_API_KEY` in `backend/.env`. |
| `WIDGET_TOKEN_SECRET is not configured` | Set it in `backend/.env` (step 3) and restart the API. |
| `permission denied` from docker | Run `sudo usermod -aG docker "$USER"`, then log out and in. |

See also: [Seed data](seed-data.md), [Configuration](configuration.md), [API reference](api.md),
[Testing](testing.md).
