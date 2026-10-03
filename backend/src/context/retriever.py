"""Backward-compatible re-exports. Prefer ``src.context.retrieval``."""

from src.context.retrieval import (
    ContextRetriever,
    RetrievedContext,
    group_tables_by_pattern,
    scan_connection_schema,
)

__all__ = [
    "ContextRetriever",
    "RetrievedContext",
    "group_tables_by_pattern",
    "scan_connection_schema",
]
