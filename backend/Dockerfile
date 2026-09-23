# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock alembic.ini ./
COPY src ./src

RUN uv sync --frozen --no-dev

# --- runtime ---

FROM python:3.12-slim

WORKDIR /app

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home /app --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/data \
    && chown -R appuser:app /app

COPY --from=builder --chown=appuser:app /app/.venv /app/.venv
COPY --from=builder --chown=appuser:app /app/src /app/src
COPY --from=builder --chown=appuser:app /app/pyproject.toml /app/pyproject.toml
COPY --from=builder --chown=appuser:app /app/alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data \
    SQLITE_URL=sqlite+aiosqlite:///./data/astrasql.db

USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
