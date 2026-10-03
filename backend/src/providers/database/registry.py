from __future__ import annotations

from typing import TYPE_CHECKING

from src.providers.database.base import BaseDatabaseProvider
from src.providers.database.mssql import MSSQLProvider
from src.providers.database.mysql import MySQLProvider
from src.providers.database.postgresql import PostgreSQLProvider
from src.providers.database.sqlite import SQLiteProvider

if TYPE_CHECKING:
    from src.storage.models import Connection

_REGISTRY: dict[str, type[BaseDatabaseProvider]] = {
    "postgresql": PostgreSQLProvider,
    "mysql": MySQLProvider,
    "mssql": MSSQLProvider,
    "sqlite": SQLiteProvider,
}

_DB_TYPE_ALIASES: dict[str, str] = {
    "postgres": "postgresql",
    "pg": "postgresql",
    "sqlserver": "mssql",
    "sql_server": "mssql",
}


def normalize_db_type(db_type: str) -> str:
    """Map common aliases to the canonical registry key (lowercase)."""
    key = (db_type or "").lower().strip()
    return _DB_TYPE_ALIASES.get(key, key)


def register_database_provider(name: str, cls: type[BaseDatabaseProvider]) -> None:
    _REGISTRY[name] = cls


def get_provider_class(db_type: str) -> type[BaseDatabaseProvider]:
    key = normalize_db_type(db_type)
    if key not in _REGISTRY:
        raise ValueError(
            f"Unknown database provider: {db_type!r}. Available: {list(_REGISTRY)}"
        )
    return _REGISTRY[key]


def get_database_provider(db_type: str, **kwargs) -> BaseDatabaseProvider:
    return get_provider_class(db_type)(**kwargs)


def list_database_types() -> list[str]:
    """Return database types that are available for new connections."""
    return [name for name, cls in _REGISTRY.items() if getattr(cls, "available", True)]


def provider_from_connection(connection: Connection) -> BaseDatabaseProvider:
    """Build a database provider from a Connection ORM row (decrypts password)."""
    from src.config.settings import get_settings
    from src.storage.crypto import decrypt_password

    settings = get_settings()
    return get_database_provider(
        connection.db_type,
        host=connection.host,
        port=connection.port,
        database=connection.database,
        username=connection.username,
        password=decrypt_password(connection.encrypted_password),
        ssl_enabled=bool(connection.ssl_enabled),
        query_timeout_seconds=settings.query_timeout_seconds,
    )
