import asyncio
import sqlite3

from src.config.settings import get_settings
from src.providers.database.base import BaseDatabaseProvider
from src.providers.database.mssql import MSSQLProvider
from src.providers.database.mysql import MySQLProvider
from src.providers.database.postgresql import PostgreSQLProvider
from src.providers.database.sqlite import SQLiteProvider


class _StubProvider(BaseDatabaseProvider):
    def dialect_name(self):
        return "x"

    def dialect_prompt_rules(self):
        return ""

    def dialect_validator_checklist(self):
        return []

    def sqlglot_dialect(self):
        return "postgres"

    def get_async_engine(self):
        raise NotImplementedError

    async def explain_query(self, sql: str) -> str:
        raise NotImplementedError

    async def test_connection(self) -> bool:
        return False

    async def list_tables(self):
        return []

    async def get_table_ddl(self, table_name: str) -> str:
        return ""

    async def get_table_schema(self, table_name: str):
        return {}

    async def execute_readonly(self, sql: str, max_rows: int = 500):
        return {"columns": [], "rows": [], "row_count": 0}

    async def close(self) -> None:
        return None


def test_base_capabilities_defaults():
    p = _StubProvider("h", 1, "d", "u", "p", query_timeout_seconds=12.5)
    assert p.supports_explain() is True
    assert p.supports_timeout() is False
    assert p.query_timeout_seconds == 12.5
    assert asyncio.run(p.sample_distinct_values("t", "c")) == []


def test_postgres_and_mysql_support_timeout():
    pg = PostgreSQLProvider("h", 5432, "d", "u", "p", query_timeout_seconds=5)
    assert pg.supports_timeout() is True
    assert pg.query_timeout_seconds == 5.0
    # PostgreSQL provider always double-quotes validated identifiers.
    assert pg.quote_ident("orders") == '"orders"'
    assert pg.quote_ident("order_items") == '"order_items"'

    my = MySQLProvider("h", 3306, "d", "u", "p", query_timeout_seconds=7)
    assert my.supports_timeout() is True
    assert my.quote_ident("order") == "`order`"


def test_sqlite_wires_settings_timeout(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("QUERY_TIMEOUT_SECONDS", "42")
    get_settings.cache_clear()
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()

    p = SQLiteProvider(database=str(db))
    assert p.supports_timeout() is True
    assert p.query_timeout_seconds == 42.0
    get_settings.cache_clear()


def test_mssql_dialect_metadata():
    m = MSSQLProvider("h", 1433, "d", "u", "p")
    assert m.available is False
    assert m.sqlglot_dialect() == "tsql"
    assert "SQL Server" in m.dialect_name()
    assert m.supports_explain() is False
    assert m.supports_timeout() is True
    assert m.quote_ident("order") == "[order]"


def test_postgres_execute_applies_statement_timeout(monkeypatch):
    """Verify SET LOCAL statement_timeout is issued when timeout > 0."""
    pg = PostgreSQLProvider("h", 5432, "d", "u", "p", query_timeout_seconds=3)
    executed: list[str] = []

    class _Result:
        def keys(self):
            return ["x"]

        def fetchmany(self, n):
            return [(1,)]

    class _Conn:
        async def execute(self, statement, *args, **kwargs):
            executed.append(str(statement))
            return _Result()

        def begin(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Engine:
        def connect(self):
            return _Conn()

    monkeypatch.setattr(pg, "get_async_engine", lambda: _Engine())
    monkeypatch.setattr(
        "src.providers.database.postgresql.refuse_unbound_sql",
        lambda sql, dialect=None: None,
    )

    async def _run():
        return await pg.execute_readonly("SELECT 1", max_rows=10)

    out = asyncio.run(_run())
    assert out["row_count"] == 1
    joined = " ".join(executed).lower()
    assert "statement_timeout" in joined
    assert "3000" in joined
