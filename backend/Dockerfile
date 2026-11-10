# Build from the repository root: the API also serves frontend/admin (and frontend/dev in DEV_MODE).
FROM python:3.12-slim

ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src ./src
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY backend/scripts ./scripts
COPY frontend/admin /app/frontend/admin
# Used only when DEV_MODE=true.
COPY frontend/dev /app/frontend/dev
COPY frontend/extensions/chat-widget/assets /app/frontend/extensions/chat-widget/assets
RUN uv sync --frozen --no-dev

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "shopchat.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
