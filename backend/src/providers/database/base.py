from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine


class BaseDatabaseProvider(ABC):
    """Abstract contract for dialect-aware database access."""

    # When False, the type is registered for future work but hidden from
    # public settings / connection creation.
    available: bool = True

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl_enabled: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.ssl_enabled = ssl_enabled
        self._engine: AsyncEngine | None = None

    @abstractmethod
    def dialect_name(self) -> str:
        """Human-readable dialect string injected into prompts."""

    @abstractmethod
    def dialect_prompt_rules(self) -> str:
        """Multi-line dialect-specific SQL generation rules."""

    @abstractmethod
    def dialect_validator_checklist(self) -> list[str]:
        """Dialect-specific checklist items for the validator LLM."""

    @abstractmethod
    def sqlglot_dialect(self) -> str:
        """Dialect string for sqlglot.parse_one(..., dialect=...)."""

    @abstractmethod
    def get_async_engine(self) -> AsyncEngine:
        """Return (and lazily create) the SQLAlchemy async engine."""

    @abstractmethod
    async def explain_query(self, sql: str) -> str:
        """Run dialect-appropriate EXPLAIN and return plan text."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Return True if a simple connectivity probe succeeds."""

    @abstractmethod
    async def list_tables(self) -> list[dict[str, Any]]:
        """List tables as ``[{name, description?}, ...]``."""

    @abstractmethod
    async def get_table_ddl(self, table_name: str) -> str:
        """Return a CREATE TABLE style DDL string for the table."""

    @abstractmethod
    async def get_table_schema(self, table_name: str) -> dict[str, Any]:
        """Return columns (types, pk, fk) plus sample rows."""

    @abstractmethod
    async def execute_readonly(
        self, sql: str, max_rows: int = 500
    ) -> dict[str, Any]:
        """Execute read-only SQL; return ``{columns, rows, row_count}``."""

    @abstractmethod
    async def close(self) -> None:
        """Dispose the async engine and release connections."""
