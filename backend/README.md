# Backend

FastAPI service, LangGraph agents, catalog indexing and the background worker.
See the [root README](../README.md) for setup and [docs](../docs) for details.

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn shopchat.api.app:app --reload
uv run arq shopchat.worker.main.WorkerSettings
uv run pytest
```
