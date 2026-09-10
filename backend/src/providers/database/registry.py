from __future__ import annotations

from typing import TYPE_CHECKING

from src.providers.database.base import BaseDatabaseProvider
from src.providers.database.mssql import MSSQLProvider
from src.providers.database.mysql import MySQLProvider
from src.providers.database.postgresql import PostgreSQLProvider

if TYPE_CHECKING:
    from src.storage.models import Connection

_REGISTRY: dict[str, type[BaseDatabaseProvider]] = {
    "postgresql": PostgreSQLProvider,
    "mysql": MySQLProvider,
    "mssql": MSSQLProvider,
}


def register_database_provider(name: str, cls: type[BaseDatabaseProvider]) -> None:
    _REGISTRY[name] = cls


def get_database_provider(db_type: str, **kwargs) -> BaseDatabaseProvider:
    key = db_type.lower().strip()
    # Accept common aliases
    aliases = {
        "postgres": "postgresql",
        "pg": "postgresql",
        "sqlserver": "mssql",
        "sql_server": "mssql",
    }
    key = aliases.get(key, key)
    if key not in _REGISTRY:
        raise ValueError(
            f"Unknown database provider: {db_type!r}. Available: {list(_REGISTRY)}"
        )
    return _REGISTRY[key](**kwargs)


def list_database_types() -> list[str]:
    return list(_REGISTRY.keys())


def provider_from_connection(connection: Connection) -> BaseDatabaseProvider:
    """Build a database provider from a Connection ORM row (decrypts password)."""
    from src.storage.crypto import decrypt_password

    return get_database_provider(
        connection.db_type,
        host=connection.host,
        port=connection.port,
        database=connection.database,
        username=connection.username,
        password=decrypt_password(connection.encrypted_password),
        ssl_enabled=bool(connection.ssl_enabled),
    )
