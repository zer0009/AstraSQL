from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.context.retrieval.index import _safe_json_loads
from src.context.schema_enrichment import discover_and_merge_relationships
from src.context.schema_linker import SchemaLinker
from src.providers.database.base import BaseDatabaseProvider
from src.storage.models import Connection, SchemaCache

logger = logging.getLogger(__name__)

async def scan_connection_schema(
    session: AsyncSession,
    connection: Connection,
    db_provider: BaseDatabaseProvider,
    *,
    rebuild_table_index: bool = True,
    progress: Callable[..., None] | None = None,
) -> list[SchemaCache]:
    """List tables from the live DB, upsert SchemaCache rows, optionally rebuild FAISS.

    Reads from the target DB first, then writes to SQLite in one pass under
    ``no_autoflush`` so mid-loop SELECTs do not flush pending INSERTs and
    collide with concurrent SQLite readers (common "database is locked" cause).

    ``progress`` is an optional callback used by background scan jobs:
    ``progress(phase=..., message=..., current_table=..., tables_total=...,
               tables_done=..., table_just_done=...)``.
    """

    def _progress(**kwargs: Any) -> None:
        if progress is not None:
            progress(**kwargs)

    _progress(phase="listing", message="Listing tables…")
    tables = await db_provider.list_tables()
    names = []
    for t in tables:
        name = t.get("name") if isinstance(t, dict) else str(t)
        if name:
            names.append(name)

    _progress(
        phase="reading",
        message=f"Reading schema for {len(names)} tables…",
        tables_total=len(names),
        tables_done=0,
    )

    # Phase 1: pull everything from the remote DB (no SQLite writes yet).
    remote: list[tuple[str, str | None, str, str]] = []
    for i, name in enumerate(names):
        _progress(
            phase="reading",
            message=f"Reading table {i + 1}/{len(names)}: {name}",
            current_table=name,
            tables_total=len(names),
            tables_done=i,
        )
        schema = await db_provider.get_table_schema(name)
        try:
            ddl = await db_provider.get_table_ddl(name)
        except Exception:
            ddl = None
        columns_json = json.dumps(schema.get("columns") or [])
        sample_rows_json = json.dumps(
            schema.get("sample_rows") or [], default=str
        )
        remote.append((name, ddl, columns_json, sample_rows_json))
        _progress(
            phase="reading",
            message=f"Read {i + 1}/{len(names)}: {name}",
            current_table=name,
            tables_total=len(names),
            tables_done=i + 1,
            table_just_done=name,
        )

    # Phase 2: upsert into SQLite without query-invoked autoflush.
    _progress(
        phase="writing",
        message="Saving schema cache…",
        current_table=None,
        tables_total=len(names),
        tables_done=len(names),
    )
    upserted: list[SchemaCache] = []
    with session.no_autoflush:
        for name, ddl, columns_json, sample_rows_json in remote:
            result = await session.execute(
                select(SchemaCache).where(
                    SchemaCache.connection_id == connection.id,
                    SchemaCache.table_name == name,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = SchemaCache(
                    connection_id=connection.id,
                    table_name=name,
                    ddl_text=ddl,
                    columns_json=columns_json,
                    sample_rows_json=sample_rows_json,
                )
                session.add(row)
            else:
                row.ddl_text = ddl
                row.columns_json = columns_json
                row.sample_rows_json = sample_rows_json
            upserted.append(row)

        connection.last_scanned_at = datetime.now(UTC).replace(tzinfo=None)
        await session.flush()

    if rebuild_table_index:
        _progress(
            phase="indexing",
            message="Building table search index…",
            current_table=None,
        )
        linker = SchemaLinker()
        await linker.build_table_index(session, connection.id)

    # Best-effort value grounding for low-cardinality string columns.
    try:
        from src.context.value_grounding import populate_example_values

        _progress(
            phase="value_grounding",
            message="Sampling distinct values for categorical columns…",
            current_table=None,
        )
        await populate_example_values(
            session, connection.id, upserted, db_provider
        )
    except Exception:
        logger.exception(
            "Value grounding failed for connection %s (scan kept)",
            connection.id,
        )

    # Best-effort relationship discovery → semantic_layer_json.
    settings = get_settings()
    if settings.relationship_discovery_enabled:
        try:
            _progress(
                phase="relationships",
                message="Discovering join relationships…",
                current_table=None,
            )
            tables_data: list[dict[str, Any]] = []
            for name, _ddl, columns_json, sample_rows_json in remote:
                tables_data.append(
                    {
                        "table_name": name,
                        "columns": _safe_json_loads(columns_json, default=[]) or [],
                        "sample_rows": _safe_json_loads(sample_rows_json, default=[])
                        or [],
                    }
                )
            await discover_and_merge_relationships(
                session,
                connection,
                tables_data,
                db_provider,
                auto_approve=settings.relationship_auto_approve,
                max_probes=50,
            )
        except Exception:
            logger.exception(
                "Relationship discovery failed for connection %s (scan kept)",
                connection.id,
            )

    _progress(
        phase="done",
        message=f"Scan complete — {len(upserted)} tables",
        tables_done=len(upserted),
        tables_total=len(names),
        current_table=None,
    )
    return upserted
