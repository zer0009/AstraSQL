from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
        *,
        query_timeout_seconds: float | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.ssl_enabled = ssl_enabled
        self._engine: AsyncEngine | None = None
        if query_timeout_seconds is None:
            from src.config.settings import get_settings

            query_timeout_seconds = get_settings().query_timeout_seconds
        self.query_timeout_seconds = float(query_timeout_seconds or 0)

    # --- Capability mixin (defaults; override per dialect) ---

    def supports_explain(self) -> bool:
        return True

    def supports_timeout(self) -> bool:
        return False

    def supports_execute_gate(self) -> bool:
        """Whether golden promotion may soft-check via execute_readonly."""
        return True

    def needs_deterministic_repair(self) -> bool:
        """Whether sqlglot deterministic repairs should run after Layer-1 syntax."""
        return False

    def quote_ident(self, name: str) -> str:
        """Quote an identifier for this dialect (default: double quotes)."""
        text_name = (name or "").replace('"', '""')
        if not text_name:
            raise ValueError("Empty SQL identifier")
        if _IDENT_RE.match(text_name):
            return text_name
        return f'"{text_name}"'

    async def sample_distinct_values(
        self,
        table: str,
        column: str,
        limit: int = 50,
    ) -> list[Any]:
        """Return up to ``limit`` distinct non-null values (default: unsupported)."""
        return []

    async def estimate_cost(self, sql: str) -> float | None:
        """Optional EXPLAIN-based cost estimate; ``None`` when unsupported."""
        return None

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
