from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from src.providers.database.base import BaseDatabaseProvider


class MSSQLProvider(BaseDatabaseProvider):
    """Microsoft SQL Server stub — dialect metadata only until aioodbc support lands."""

    available = False

    def dialect_name(self) -> str:
        return "Microsoft SQL Server 2022"

    def dialect_prompt_rules(self) -> str:
        return """
- Date arithmetic: DATEADD(day, 30, col), DATEDIFF(day, col1, col2), DATEPART(year, col)
- Case-insensitive matching: depends on collation; use LOWER()/UPPER() for explicit case-insensitivity
- Identifier quoting: square brackets [column_name]
- Pagination: OFFSET {m} ROWS FETCH NEXT {n} ROWS ONLY (or TOP {n} for simple limits)
- Concatenation: + operator or CONCAT()
- Prefer CTEs (WITH clause) over deeply nested subqueries
- Window functions: supported — ROW_NUMBER(), LAG(), LEAD(), RANK()
""".strip()

    def dialect_validator_checklist(self) -> list[str]:
        return [
            "DATEADD / DATEDIFF / DATEPART used correctly (not DATE_TRUNC or DATE_FORMAT)",
            "TOP or OFFSET/FETCH present for list queries unless aggregation covers all rows",
            "Square brackets used for reserved identifiers when needed",
            "LIMIT keyword not used (SQL Server does not support LIMIT)",
        ]

    def sqlglot_dialect(self) -> str:
        return "tsql"

    def get_async_engine(self) -> AsyncEngine:
        raise NotImplementedError("MSSQLProvider is not implemented yet")

    async def explain_query(self, sql: str) -> str:
        raise NotImplementedError("MSSQLProvider is not implemented yet")

    async def test_connection(self) -> bool:
        raise NotImplementedError("MSSQLProvider is not implemented yet")

    async def list_tables(self) -> list[dict[str, Any]]:
        raise NotImplementedError("MSSQLProvider is not implemented yet")

    async def get_table_ddl(self, table_name: str) -> str:
        raise NotImplementedError("MSSQLProvider is not implemented yet")

    async def get_table_schema(self, table_name: str) -> dict[str, Any]:
        raise NotImplementedError("MSSQLProvider is not implemented yet")

    async def execute_readonly(
        self, sql: str, max_rows: int = 500
    ) -> dict[str, Any]:
        raise NotImplementedError("MSSQLProvider is not implemented yet")

    async def close(self) -> None:
        return None
