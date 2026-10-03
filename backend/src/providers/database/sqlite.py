"""Read-only SQLite provider for local benchmark databases (Spider, etc.)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import sqlglot
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlglot import exp

from src.agent.sql_guards import refuse_unbound_sql
from src.providers.database.base import BaseDatabaseProvider

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_ident(name: str) -> str:
    """Quote a SQLite identifier (handles spaces and reserved words).

    Always double-quote: names like ``order`` / ``group`` are valid table
    names but unquoted PRAGMA/SELECT would fail as SQL keywords.
    """
    text_name = (name or "").replace('"', '""')
    if not text_name:
        raise ValueError("Empty SQL identifier")
    return f'"{text_name}"'


class SQLiteProvider(BaseDatabaseProvider):
    """File-backed SQLite access via SQLAlchemy + aiosqlite (read-only)."""

    available: bool = False  # not listed in the public connection UI

    def __init__(
        self,
        host: str = "local",
        port: int = 0,
        database: str = "",
        username: str = "",
        password: str = "",
        ssl_enabled: bool = False,
        *,
        query_timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(
            host=host or "local",
            port=int(port or 0),
            database=database,
            username=username or "",
            password=password or "",
            ssl_enabled=ssl_enabled,
            query_timeout_seconds=query_timeout_seconds,
        )

    def supports_timeout(self) -> bool:
        # Uses PRAGMA busy_timeout (wired from query_timeout_seconds).
        return True

    def needs_deterministic_repair(self) -> bool:
        return True

    def quote_ident(self, name: str) -> str:
        return _quote_ident(name)

    def dialect_name(self) -> str:
        return "SQLite"

    def dialect_prompt_rules(self) -> str:
        return """
- Use SQLite syntax only. Do not use ILIKE (use LIKE with lower() instead).
- Date/time: use strftime('%Y', col), date(col), datetime(col).
- Pagination: LIMIT {n} OFFSET {m}. There is no TOP.
- Identifier quoting: double quotes for names with spaces or reserved words.
- No RIGHT JOIN / FULL OUTER JOIN on older SQLite — prefer LEFT JOIN.
- String concat: || operator.
- This runner binds no parameters. Write a literal only when the question supplies the value.
- Auto-increment primary keys often appear as INTEGER PRIMARY KEY.
""".strip()

    def dialect_validator_checklist(self) -> list[str]:
        return [
            "No ILIKE — use LIKE / lower() for case-insensitive matching",
            "No RIGHT JOIN or FULL OUTER JOIN unless confirmed supported",
            "Date functions use strftime / date / datetime (not DATE_TRUNC)",
            "LIMIT present for list queries unless aggregation covers all rows",
            "No bind placeholders: reject $1, :name, or ?",
        ]

    def sqlglot_dialect(self) -> str:
        return "sqlite"

    def _db_path(self) -> Path:
        path = Path(self.database).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"SQLite database not found: {path}")
        return path

    def _connection_url(self) -> str:
        path = self._db_path()
        # Absolute path with forward slashes works on Windows and POSIX.
        return f"sqlite+aiosqlite:///{path.as_posix()}"

    def get_async_engine(self) -> AsyncEngine:
        if self._engine is None:
            engine = create_async_engine(
                self._connection_url(),
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )

            timeout_ms = max(1, int(self.query_timeout_seconds * 1000))

            @event.listens_for(engine.sync_engine, "connect")
            def _on_connect(dbapi_conn: Any, _connection_record: Any) -> None:  # noqa: ANN401
                cursor = dbapi_conn.cursor()
                try:
                    cursor.execute("PRAGMA query_only=ON")
                    cursor.execute(f"PRAGMA busy_timeout={timeout_ms}")
                finally:
                    cursor.close()

            self._engine = engine
        return self._engine

    async def test_connection(self) -> bool:
        try:
            engine = self.get_async_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def explain_query(self, sql: str) -> str:
        refuse_unbound_sql(sql, self.sqlglot_dialect())
        cleaned = sql.strip().rstrip(";")
        engine = self.get_async_engine()
        async with engine.connect() as conn:
            result = await conn.execute(text(f"EXPLAIN QUERY PLAN {cleaned}"))
            rows = result.fetchall()
        return "\n".join(" | ".join(str(c) for c in row) for row in rows)

    async def estimate_cost(self, sql: str) -> float | None:
        """Heuristic cost from EXPLAIN QUERY PLAN (count of SCAN ops)."""
        try:
            plan = await self.explain_query(sql)
        except Exception:
            return None
        if not plan:
            return 0.0
        # SQLite plans mention SCAN for full-table scans; SEARCH for indexes.
        scan_ops = sum(
            1
            for line in plan.splitlines()
            if re.search(r"\bSCAN\b", line, re.IGNORECASE)
        )
        return float(scan_ops)

    async def list_tables(self) -> list[dict[str, Any]]:
        engine = self.get_async_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    """
                )
            )
            names = [row[0] for row in result.fetchall()]
        return [{"name": n, "description": None} for n in names]

    async def get_table_schema(self, table_name: str) -> dict[str, Any]:
        engine = self.get_async_engine()
        ident = _quote_ident(table_name)
        async with engine.connect() as conn:
            cols_result = await conn.execute(text(f"PRAGMA table_info({ident})"))
            col_rows = cols_result.fetchall()
            if not col_rows:
                raise ValueError(f"Table not found: {table_name}")
            fk_result = await conn.execute(text(f"PRAGMA foreign_key_list({ident})"))
            fk_rows = fk_result.fetchall()
            sample_result = await conn.execute(
                text(f"SELECT * FROM {ident} LIMIT 3")
            )
            sample_cols = list(sample_result.keys())
            sample_raw = sample_result.fetchall()

        # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
        columns: list[dict[str, Any]] = []
        pk_cols: list[str] = []
        for row in col_rows:
            name = row[1]
            col_type = row[2] or "TEXT"
            notnull = bool(row[3])
            default = row[4]
            is_pk = bool(row[5])
            if is_pk:
                pk_cols.append(name)
            columns.append(
                {
                    "name": name,
                    "type": col_type,
                    "nullable": not notnull,
                    "default": default,
                    "primary_key": is_pk,
                    "foreign_key": None,
                }
            )

        # PRAGMA foreign_key_list: id, seq, table, from, to, on_update, on_delete, match
        fks: list[dict[str, str]] = []
        fk_by_col: dict[str, dict[str, str]] = {}
        for row in fk_rows:
            fk = {
                "column_name": row[3],
                "foreign_table_name": row[2],
                "foreign_column_name": row[4],
            }
            fks.append(fk)
            fk_by_col[row[3]] = {
                "table": row[2],
                "column": row[4],
            }
        for col in columns:
            if col["name"] in fk_by_col:
                col["foreign_key"] = fk_by_col[col["name"]]

        samples = [dict(zip(sample_cols, row, strict=False)) for row in sample_raw]
        return {
            "table_name": table_name,
            "columns": columns,
            "primary_keys": pk_cols,
            "foreign_keys": fks,
            "sample_rows": samples,
        }

    async def get_table_ddl(self, table_name: str) -> str:
        engine = self.get_async_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT sql FROM sqlite_master
                    WHERE type = 'table' AND name = :name
                    """
                ),
                {"name": table_name},
            )
            row = result.fetchone()
        if row and row[0]:
            schema = await self.get_table_schema(table_name)
            ddl = str(row[0])
            samples = schema.get("sample_rows") or []
            if samples:
                sample_lines = [
                    ", ".join(f"{k}={v!r}" for k, v in sample.items())
                    for sample in samples
                ]
                ddl += (
                    f"\n/* Sample rows (3 rows from {table_name}):\n"
                    + "\n".join(sample_lines)
                    + "\n*/"
                )
            return ddl
        # Fallback synthetic DDL
        schema = await self.get_table_schema(table_name)
        lines: list[str] = []
        for col in schema["columns"]:
            parts = [f"    {_quote_ident(col['name'])}  {col['type']}"]
            if col["primary_key"]:
                parts.append("PRIMARY KEY")
            if not col["nullable"] and not col["primary_key"]:
                parts.append("NOT NULL")
            lines.append(" ".join(parts))
        body = ",\n".join(lines)
        return f"CREATE TABLE {_quote_ident(table_name)} (\n{body}\n);"

    def _ensure_outer_limit(self, sql: str, max_rows: int) -> str:
        cleaned = sql.strip().rstrip(";")
        try:
            parsed = sqlglot.parse_one(cleaned, dialect=self.sqlglot_dialect())
            # Only check the outermost select for LIMIT.
            if isinstance(parsed, exp.Select) and parsed.args.get("limit") is None:
                return f"{cleaned}\nLIMIT {int(max_rows)}"
            if isinstance(parsed, exp.With):
                this = parsed.this
                if isinstance(this, exp.Select) and this.args.get("limit") is None:
                    return f"SELECT * FROM (\n{cleaned}\n) AS _astrasql_lim LIMIT {int(max_rows)}"
            return cleaned
        except Exception:
            if re.search(r"\blimit\b", cleaned, re.IGNORECASE) is None:
                return f"{cleaned}\nLIMIT {int(max_rows)}"
            return cleaned

    async def execute_readonly(
        self, sql: str, max_rows: int = 500
    ) -> dict[str, Any]:
        refuse_unbound_sql(sql, self.sqlglot_dialect())
        limited_sql = self._ensure_outer_limit(sql, max_rows)
        engine = self.get_async_engine()
        async with engine.connect() as conn:
            result = await conn.execute(text(limited_sql))
            columns = list(result.keys())
            rows_raw = result.fetchmany(max_rows)
            rows = [
                {col: val for col, val in zip(columns, row, strict=False)}
                for row in rows_raw
            ]
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }

    async def sample_distinct_values(
        self,
        table: str,
        column: str,
        limit: int = 50,
    ) -> list[Any]:
        table_q = _quote_ident(table)
        col_q = _quote_ident(column)
        lim = max(1, int(limit))
        sql = (
            f"SELECT DISTINCT {col_q} AS v FROM {table_q} "
            f"WHERE {col_q} IS NOT NULL "
            f"LIMIT {lim}"
        )
        result = await self.execute_readonly(sql, max_rows=lim)
        values: list[Any] = []
        for row in result.get("rows") or []:
            if isinstance(row, dict):
                raw = row.get("v")
                if raw is None and row:
                    raw = next(iter(row.values()), None)
            else:
                raw = row
            if raw is not None:
                values.append(raw)
        return values

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


def open_sqlite_file(path: str | Path, **kwargs: Any) -> SQLiteProvider:
    """Convenience constructor for eval scripts."""
    return SQLiteProvider(
        host="local",
        port=0,
        database=str(path),
        username="",
        password="",
        **kwargs,
    )
