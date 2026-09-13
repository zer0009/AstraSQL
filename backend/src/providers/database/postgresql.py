from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlglot import exp

from src.providers.database.base import BaseDatabaseProvider

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return f'"{name}"'


def _format_type(data_type: str, char_max: int | None, numeric_precision: int | None, numeric_scale: int | None) -> str:
    dt = (data_type or "").upper()
    if dt in {"CHARACTER VARYING", "VARCHAR", "CHARACTER", "CHAR"} and char_max is not None:
        base = "VARCHAR" if "VAR" in dt or dt == "CHARACTER VARYING" else "CHAR"
        return f"{base}({char_max})"
    if dt in {"NUMERIC", "DECIMAL"} and numeric_precision is not None:
        if numeric_scale is not None:
            return f"{dt}({numeric_precision},{numeric_scale})"
        return f"{dt}({numeric_precision})"
    return data_type or "UNKNOWN"


def _flatten_cell(value: Any) -> Any:
    """Turn dict-valued JSONB cells into a readable string (language-agnostic).

    asyncpg returns jsonb as Python dict. Prefer the first non-empty string
    value so UI/answers never show raw ``{"key": "..."}`` objects. No language
    keys are hardcoded — insertion order from the DB driver is used.
    """
    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, str) and v.strip():
                return v
        return str(value)
    return value


class PostgreSQLProvider(BaseDatabaseProvider):
    """PostgreSQL access via SQLAlchemy + asyncpg."""

    def dialect_name(self) -> str:
        return "PostgreSQL 16"

    def dialect_prompt_rules(self) -> str:
        return """
- Date arithmetic: DATE_TRUNC('month', col), col + INTERVAL '30 days', EXTRACT(year FROM col)
- Case-insensitive matching: use ILIKE instead of LIKE
- Identifier quoting: double quotes only when names contain spaces or reserved words
- Pagination: LIMIT {n} OFFSET {m}
- Concatenation: || operator or CONCAT()
- Prefer CTEs (WITH clause) over deeply nested subqueries
- Window functions: supported — ROW_NUMBER(), LAG(), LEAD(), RANK()
- JSONB/JSON operators (->>, ->): ONLY on columns whose schema type is jsonb or json.
  Never use ->> or -> on character varying, text, varchar, char, integer, or other
  non-JSON types — PostgreSQL will raise "operator does not exist".
  For plain text/varchar name columns, SELECT the column directly (e.g. rcs.name).
  For jsonb/json columns only: never reference them bare in SELECT — that returns a
  raw JSON object. Always use ->> to extract text (e.g. col->>'some_key'). When a
  JSONB column stores translated display names, use COALESCE across keys that appear
  in the sample data shown in the schema (COALESCE(col->>'key_a', col->>'key_b')),
  preferring the first non-null non-empty string. Pick key names only from sample
  data — do not invent keys.
""".strip()

    def dialect_validator_checklist(self) -> list[str]:
        return [
            "DATE_TRUNC / INTERVAL / EXTRACT used correctly (not MySQL DATE_FORMAT or DATEPART)",
            "ILIKE used for case-insensitive matching (not MySQL's implicit case-insensitivity)",
            "Column aliases in HAVING reference the expression, not the alias name",
            "LIMIT present for list queries unless aggregation covers all rows",
            "JSONB bare select: if any column in SELECT is typed jsonb/json and is referenced without ->> or ->, flag it — the result will be a raw JSON string, not a human-readable value",
            "JSONB type guard: if ->> or -> is used on a column typed character varying, text, varchar, or any non-json/jsonb type, flag it and rewrite to use the column directly (no JSON operators)",
        ]

    def sqlglot_dialect(self) -> str:
        return "postgres"

    def _connection_url(self) -> str:
        user = quote_plus(self.username)
        password = quote_plus(self.password)
        database = quote_plus(self.database)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.host}:{self.port}/{database}"
        )

    def get_async_engine(self) -> AsyncEngine:
        if self._engine is None:
            connect_args: dict[str, Any] = {}
            if self.ssl_enabled:
                # asyncpg accepts True / SSLContext; True enables default TLS.
                connect_args["ssl"] = True
            self._engine = create_async_engine(
                self._connection_url(),
                connect_args=connect_args,
                pool_pre_ping=True,
            )
        return self._engine

    async def explain_query(self, sql: str) -> str:
        engine = self.get_async_engine()
        cleaned = sql.strip().rstrip(";")
        async with engine.connect() as conn:
            result = await conn.execute(text(f"EXPLAIN (FORMAT TEXT) {cleaned}"))
            lines = [row[0] for row in result.fetchall()]
        return "\n".join(lines)

    async def test_connection(self) -> bool:
        engine = self.get_async_engine()
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def list_tables(self) -> list[dict[str, Any]]:
        engine = self.get_async_engine()
        query = text(
            """
            SELECT
                t.table_name AS name,
                d.description AS description
            FROM information_schema.tables t
            LEFT JOIN pg_catalog.pg_class c
              ON c.relname = t.table_name
            LEFT JOIN pg_catalog.pg_namespace n
              ON n.oid = c.relnamespace
             AND n.nspname = t.table_schema
            LEFT JOIN pg_catalog.pg_description d
              ON d.objoid = c.oid
             AND d.objsubid = 0
            WHERE t.table_schema = 'public'
              AND t.table_type = 'BASE TABLE'
              AND (c.relkind IS NULL OR c.relkind = 'r')
            ORDER BY t.table_name
            """
        )
        async with engine.connect() as conn:
            result = await conn.execute(query)
            rows = result.mappings().all()
        return [
            {"name": row["name"], "description": row["description"]}
            for row in rows
        ]

    async def _fetch_columns(self, conn: Any, table_name: str) -> list[dict[str, Any]]:
        result = await conn.execute(
            text(
                """
                SELECT
                    column_name,
                    data_type,
                    udt_name,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale,
                    is_nullable,
                    column_default,
                    ordinal_position
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                ORDER BY ordinal_position
                """
            ),
            {"table_name": table_name},
        )
        return [dict(row) for row in result.mappings().all()]

    async def _fetch_primary_keys(self, conn: Any, table_name: str) -> set[str]:
        result = await conn.execute(
            text(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = :table_name
                  AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
                """
            ),
            {"table_name": table_name},
        )
        return {row[0] for row in result.fetchall()}

    async def _fetch_foreign_keys(
        self, conn: Any, table_name: str
    ) -> list[dict[str, str]]:
        result = await conn.execute(
            text(
                """
                SELECT
                    kcu.column_name AS column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                  AND tc.table_name = :table_name
                ORDER BY kcu.ordinal_position
                """
            ),
            {"table_name": table_name},
        )
        return [dict(row) for row in result.mappings().all()]

    async def _fetch_sample_rows(
        self, conn: Any, table_name: str, limit: int = 3
    ) -> list[dict[str, Any]]:
        ident = _quote_ident(table_name)
        result = await conn.execute(
            text(f"SELECT * FROM {ident} LIMIT :limit"),
            {"limit": limit},
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]

    async def get_table_schema(self, table_name: str) -> dict[str, Any]:
        _quote_ident(table_name)  # validate
        engine = self.get_async_engine()
        async with engine.connect() as conn:
            raw_columns = await self._fetch_columns(conn, table_name)
            if not raw_columns:
                raise ValueError(f"Table not found: {table_name}")
            pk_cols = await self._fetch_primary_keys(conn, table_name)
            fks = await self._fetch_foreign_keys(conn, table_name)
            fk_by_col = {fk["column_name"]: fk for fk in fks}
            samples = await self._fetch_sample_rows(conn, table_name, limit=3)

        columns: list[dict[str, Any]] = []
        for col in raw_columns:
            name = col["column_name"]
            fk = fk_by_col.get(name)
            columns.append(
                {
                    "name": name,
                    "type": _format_type(
                        col["data_type"],
                        col["character_maximum_length"],
                        col["numeric_precision"],
                        col["numeric_scale"],
                    ),
                    "udt_name": col["udt_name"],
                    "nullable": col["is_nullable"] == "YES",
                    "default": col["column_default"],
                    "primary_key": name in pk_cols,
                    "foreign_key": (
                        {
                            "table": fk["foreign_table_name"],
                            "column": fk["foreign_column_name"],
                        }
                        if fk
                        else None
                    ),
                }
            )

        return {
            "table_name": table_name,
            "columns": columns,
            "primary_keys": sorted(pk_cols),
            "foreign_keys": fks,
            "sample_rows": samples,
        }

    async def get_table_ddl(self, table_name: str) -> str:
        schema = await self.get_table_schema(table_name)
        lines: list[str] = []
        for col in schema["columns"]:
            parts = [f"    {col['name']}  {col['type']}"]
            if col["primary_key"]:
                parts.append("PRIMARY KEY")
            if not col["nullable"] and not col["primary_key"]:
                parts.append("NOT NULL")
            if col["foreign_key"]:
                fk = col["foreign_key"]
                parts.append(f"-- FK to {fk['table']}.{fk['column']}")
            lines.append(" ".join(parts))

        for fk in schema["foreign_keys"]:
            lines.append(
                f"    FOREIGN KEY ({fk['column_name']}) "
                f"REFERENCES {fk['foreign_table_name']}({fk['foreign_column_name']})"
            )

        body = ",\n".join(lines)
        ddl = f"CREATE TABLE {table_name} (\n{body}\n);"

        samples = schema.get("sample_rows") or []
        if samples:
            sample_lines = []
            for row in samples:
                sample_lines.append(
                    ", ".join(f"{k}={v!r}" for k, v in row.items())
                )
            ddl += (
                f"\n/* Sample rows (3 rows from {table_name}):\n"
                + "\n".join(sample_lines)
                + "\n*/"
            )
        return ddl

    def _ensure_limit(self, sql: str, max_rows: int) -> str:
        cleaned = sql.strip().rstrip(";")
        try:
            parsed = sqlglot.parse_one(cleaned, dialect=self.sqlglot_dialect())
            if parsed.find(exp.Limit) is None:
                return f"{cleaned}\nLIMIT {int(max_rows)}"
            return cleaned
        except Exception:
            if re.search(r"\blimit\b", cleaned, re.IGNORECASE) is None:
                return f"{cleaned}\nLIMIT {int(max_rows)}"
            return cleaned

    async def execute_readonly(
        self, sql: str, max_rows: int = 500
    ) -> dict[str, Any]:
        limited_sql = self._ensure_limit(sql, max_rows)
        engine = self.get_async_engine()
        async with engine.connect() as conn:
            # BEGIN then SET TRANSACTION READ ONLY rejects DML in this txn.
            async with conn.begin():
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                result = await conn.execute(text(limited_sql))
                columns = list(result.keys())
                rows_raw = result.fetchmany(max_rows)
                rows = [
                    {
                        col: _flatten_cell(val)
                        for col, val in zip(columns, row)
                    }
                    for row in rows_raw
                ]
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
