"""Optional live Postgres smoke tests.

Skipped unless ``ASTRASQL_PG_DSN`` is set (used by the CI postgres job).

Expected DSN form (asyncpg):
  postgresql+asyncpg://user:pass@host:5432/dbname
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

from src.providers.database.postgresql import PostgreSQLProvider
from src.providers.database.registry import normalize_db_type

pytestmark = pytest.mark.postgres

_DSN = (os.environ.get("ASTRASQL_PG_DSN") or "").strip()


def _skip_without_dsn() -> None:
    if not _DSN:
        pytest.skip("ASTRASQL_PG_DSN not set")


def _provider_from_dsn() -> PostgreSQLProvider:
    """Parse a SQLAlchemy-style async DSN into provider kwargs."""
    raw = _DSN.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(raw)
    if not parsed.hostname or not parsed.path:
        raise ValueError(f"Invalid ASTRASQL_PG_DSN: {_DSN!r}")
    database = parsed.path.lstrip("/")
    return PostgreSQLProvider(
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=database,
        username=parsed.username or "",
        password=parsed.password or "",
        ssl_enabled=False,
        query_timeout_seconds=10.0,
    )


def test_normalize_db_type_aliases() -> None:
    assert normalize_db_type("postgres") == "postgresql"
    assert normalize_db_type("pg") == "postgresql"
    assert normalize_db_type("POSTGRESQL") == "postgresql"


@pytest.mark.asyncio
async def test_postgres_provider_smoke() -> None:
    _skip_without_dsn()
    provider = _provider_from_dsn()
    try:
        assert provider.available is True
        assert provider.sqlglot_dialect() == "postgres"
        assert provider.supports_execute_gate() is True
        assert provider.needs_deterministic_repair() is False
        assert await provider.test_connection() is True
        result = await provider.execute_readonly("SELECT 1 AS n", max_rows=1)
        assert result["row_count"] == 1
        assert result["columns"] == ["n"]
        assert result["rows"][0]["n"] == 1
    finally:
        await provider.close()
