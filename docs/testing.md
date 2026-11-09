# Testing

No test calls OpenAI. The suite forces `LLM_CALLS_ENABLED=false` and uses fake models.

## Backend

```bash
docker compose up -d postgres redis
cd backend
uv sync
SHOPCHAT_POSTGRES_PORT=5432 SHOPCHAT_REDIS_PORT=6379 uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src evals
```

The suite creates its own `shopchat_test` database and never touches your development data.

| Folder | Covers |
| --- | --- |
| `backend/tests/unit` | Agents with fake models, filters, facts, scoring, signatures, configuration |
| `backend/tests/integration` | Postgres, row-level security, retrieval, API endpoints, OAuth, webhooks, worker |

## Frontend

```bash
cd frontend
npm ci
npm test
npm run lint
```

`frontend/tests/widget` runs the widget in jsdom.

## Evaluation

The evaluation does call OpenAI and costs money, so it is separate from the tests. See
[evaluation.md](evaluation.md).
