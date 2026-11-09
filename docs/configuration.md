# Configuration

Settings are read from the environment or `backend/.env`. Never commit that file.

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Runtime connection, as the `shopchat_app` role |
| `DATABASE_OWNER_URL` | Yes | Migrations, as the `shopchat_owner` role |
| `REDIS_URL` | Yes | Sessions and jobs |
| `APP_URL` | Yes | Public HTTPS URL of the backend |
| `LLM_CALLS_ENABLED` | No | Hard switch for all OpenAI calls; defaults to `false` |
| `VOICE_ENABLED` | No | Global voice switch; defaults to `false` |
| `OPENAI_API_KEY` | For AI features | OpenAI credential |
| `OPENAI_MODEL_FAST` | For AI features | Routing and planning, for example `gpt-4o-mini` |
| `OPENAI_MODEL_SMART` | For AI features | Choosing products and reading images |
| `OPENAI_MODEL_EMBEDDING` | For AI features | Use `text-embedding-3-small` to match the seed data |
| `OPENAI_MODEL_STT` | For voice | Speech to text |
| `OPENAI_MODEL_TTS` | For voice | Text to speech |
| `SHOPIFY_API_KEY` | For Shopify | App client ID |
| `SHOPIFY_API_SECRET` | For Shopify | App secret |
| `SHOPIFY_API_VERSION` | No | Defaults to `2026-10` |
| `TOKEN_ENCRYPTION_KEY` | For Shopify | Fernet key that encrypts store tokens |
| `WIDGET_TOKEN_SECRET` | For the widget | Signs widget session tokens |
| `SHOPCHAT_APP_PASSWORD` | No | Password for the runtime role in migrations |

## Docker Compose variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `SHOPCHAT_POSTGRES_PORT` | `5432` | Host port for Postgres |
| `SHOPCHAT_REDIS_PORT` | `6379` | Host port for Redis |
| `SHOPCHAT_API_PORT` | `8000` | Host port for the API |

## Features for each store

| Feature | Default |
| --- | --- |
| Image upload | On |
| Skin analysis | On when the catalog contains skincare |
| Voice | Off, and needs `VOICE_ENABLED=true` |
