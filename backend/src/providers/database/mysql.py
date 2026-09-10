from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from src.providers.database.base import BaseDatabaseProvider


class MySQLProvider(BaseDatabaseProvider):
    """MySQL stub — dialect metadata only until aiomysql support lands."""

    def dialect_name(self) -> str:
        return "MySQL 8.0"

    def dialect_prompt_rules(self) -> str:
        return """
- Date arithmetic: DATE_ADD(col, INTERVAL 30 DAY), DATEDIFF(col1, col2), DATE_FORMAT(col, '%Y-%m')
- Case-insensitive matching: LIKE is case-insensitive on most collations by default
- Identifier quoting: backticks `column_name`
- Pagination: LIMIT {n} OFFSET {m}
- Concatenation: CONCAT() (avoid || which is logical OR in MySQL by default)
- Prefer CTEs (WITH clause) over deeply nested subqueries when available
- Window functions: supported since MySQL 8.0 — ROW_NUMBER(), LAG(), LEAD(), RANK()
""".strip()

    def dialect_validator_checklist(self) -> list[str]:
        return [
            "DATE_ADD / DATE_FORMAT / DATEDIFF used correctly (not PostgreSQL DATE_TRUNC or INTERVAL 'n days')",
            "Backticks used for reserved identifiers when needed",
            "|| not used for string concatenation (use CONCAT)",
            "LIMIT present for list queries unless aggregation covers all rows",
        ]

    def sqlglot_dialect(self) -> str:
        return "mysql"

    def get_async_engine(self) -> AsyncEngine:
        raise NotImplementedError("MySQLProvider is not implemented yet")

    async def explain_query(self, sql: str) -> str:
        raise NotImplementedError("MySQLProvider is not implemented yet")

    async def test_connection(self) -> bool:
        raise NotImplementedError("MySQLProvider is not implemented yet")

    async def list_tables(self) -> list[dict[str, Any]]:
        raise NotImplementedError("MySQLProvider is not implemented yet")

    async def get_table_ddl(self, table_name: str) -> str:
        raise NotImplementedError("MySQLProvider is not implemented yet")

    async def get_table_schema(self, table_name: str) -> dict[str, Any]:
        raise NotImplementedError("MySQLProvider is not implemented yet")

    async def execute_readonly(
        self, sql: str, max_rows: int = 500
    ) -> dict[str, Any]:
        raise NotImplementedError("MySQLProvider is not implemented yet")

    async def close(self) -> None:
        return None
