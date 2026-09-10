from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.context.business_rules import BusinessRulesStore
from src.context.golden_records import GoldenRecordsStore
from src.context.schema_enrichment import SchemaEnrichmentStore
from src.context.schema_linker import SchemaLinker
from src.providers.database.base import BaseDatabaseProvider
from src.storage.models import Connection, SchemaCache


@dataclass
class RetrievedContext:
    enriched_schema: str
    business_rules: str
    golden_records_text: str
    selected_tables: list[str]
    selected_columns: list[dict]
    steps: list[dict] = field(default_factory=list)


def _safe_json_loads(raw: Optional[str], default: Any = None) -> Any:
    if raw is None or raw == "":
        return default if default is not None else None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else None


async def scan_connection_schema(
    session: AsyncSession,
    connection: Connection,
    db_provider: BaseDatabaseProvider,
    *,
    rebuild_table_index: bool = True,
    progress: Optional[Callable[..., None]] = None,
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

        connection.last_scanned_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.flush()

    if rebuild_table_index:
        _progress(
            phase="indexing",
            message="Building table search index…",
            current_table=None,
        )
        linker = SchemaLinker()
        await linker.build_table_index(session, connection.id)

    _progress(
        phase="done",
        message=f"Scan complete — {len(upserted)} tables",
        tables_done=len(upserted),
        tables_total=len(names),
        current_table=None,
    )
    return upserted


class ContextRetriever:
    """Orchestrates schema linking, enrichments, rules, and golden records."""

    def __init__(self) -> None:
        self.enrichments = SchemaEnrichmentStore()
        self.rules = BusinessRulesStore()
        self.golden = GoldenRecordsStore()
        self.linker = SchemaLinker()
        self._settings = get_settings()

    async def get(
        self,
        session: AsyncSession,
        connection_id: str,
        question: str,
        db_provider: BaseDatabaseProvider,
    ) -> RetrievedContext:
        steps: list[dict] = []

        # 1. Load schema cache (scan if empty)
        result = await session.execute(
            select(SchemaCache).where(SchemaCache.connection_id == connection_id)
        )
        caches = list(result.scalars().all())

        if not caches:
            connection = await session.get(Connection, connection_id)
            if connection is None:
                raise ValueError(f"Connection not found: {connection_id}")
            steps.append(
                {
                    "step": "schema_scan",
                    "detail": "Schema cache empty; scanning connection",
                }
            )
            caches = await scan_connection_schema(session, connection, db_provider)

        enrich_map = await self.enrichments.get_for_tables(
            session,
            connection_id,
            [c.table_name for c in caches],
        )

        all_table_names = [c.table_name for c in caches]
        cache_by_name = {c.table_name: c for c in caches}

        # 2. SchemaLinker coarse + fine
        candidates = await self.linker.coarse_filter(
            connection_id,
            question,
            all_table_names,
            top_k=self._settings.faiss_top_k_tables,
        )
        steps.append(
            {
                "step": "schema_coarse",
                "detail": (
                    f"Coarse filter selected {len(candidates)} of "
                    f"{len(all_table_names)} tables"
                ),
                "tables": candidates,
            }
        )

        candidate_payload: list[dict[str, Any]] = []
        for name in candidates:
            cache = cache_by_name.get(name)
            columns = _safe_json_loads(
                cache.columns_json if cache else None, default=[]
            ) or []
            table_enrich = enrich_map.get(name, {})
            col_enrich = table_enrich.get("columns") or {}
            enriched_cols = []
            for col in columns:
                col_name = col.get("name") or col.get("column_name")
                meta = col_enrich.get(col_name, {}) if col_name else {}
                enriched_cols.append(
                    {
                        **col,
                        "description": meta.get("description")
                        or col.get("description"),
                    }
                )
            candidate_payload.append(
                {
                    "name": name,
                    "table_name": name,
                    "description": table_enrich.get("description") or "",
                    "columns": enriched_cols,
                }
            )

        fine = await self.linker.fine_select(question, candidate_payload)
        selected_tables: list[str] = fine.get("tables") or []
        selected_columns: list[dict] = fine.get("columns") or []
        steps.append(
            {
                "step": "schema_fine",
                "detail": (
                    f"Fine select linked {len(selected_tables)} tables, "
                    f"{len(selected_columns)} columns"
                ),
                "tables": selected_tables,
                "columns": selected_columns,
            }
        )

        # 3. Format enriched schema for selected tables (filter columns when known)
        cols_by_table: dict[str, set[str]] = {}
        for item in selected_columns:
            t = item.get("table")
            c = item.get("column")
            if t and c:
                cols_by_table.setdefault(t, set()).add(c)

        tables_data: list[dict[str, Any]] = []
        for name in selected_tables:
            cache = cache_by_name.get(name)
            columns = _safe_json_loads(
                cache.columns_json if cache else None, default=[]
            ) or []
            allowed = cols_by_table.get(name)
            if allowed:
                # Keep PK/FK columns even if not explicitly selected
                filtered = []
                for col in columns:
                    col_name = col.get("name") or col.get("column_name")
                    if (
                        col_name in allowed
                        or col.get("primary_key")
                        or col.get("foreign_key")
                    ):
                        filtered.append(col)
                columns = filtered or columns

            sample_rows = _safe_json_loads(
                cache.sample_rows_json if cache else None, default=[]
            ) or []
            tables_data.append(
                {
                    "table_name": name,
                    "columns": columns,
                    "sample_rows": sample_rows,
                }
            )

        enriched_schema = await self.enrichments.format_enriched_schema(
            session, connection_id, tables_data
        )
        steps.append(
            {
                "step": "enrichment",
                "detail": f"Formatted enriched schema for {len(tables_data)} tables",
            }
        )

        # 4. Business rules
        business_rules = await self.rules.get_rules_text(session, connection_id)
        steps.append(
            {
                "step": "business_rules",
                "detail": (
                    "Loaded business rules"
                    if business_rules != "(none)"
                    else "No business rules"
                ),
            }
        )

        # 5. Golden records
        golden_hits = await self.golden.search(
            session,
            connection_id,
            question,
            top_k=self._settings.golden_records_top_k,
        )
        golden_records_text = self.golden.format_few_shot(golden_hits)
        steps.append(
            {
                "step": "golden_records",
                "detail": f"Retrieved {len(golden_hits)} similar golden records",
            }
        )

        return RetrievedContext(
            enriched_schema=enriched_schema,
            business_rules=business_rules,
            golden_records_text=golden_records_text,
            selected_tables=selected_tables,
            selected_columns=selected_columns,
            steps=steps,
        )
