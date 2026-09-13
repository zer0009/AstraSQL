"""Auto-generate table/column descriptions after a schema scan.

Cost-optimized path: cheap model, batched tables, parallel calls, DDL-hash skip,
and trivial-column filtering before the LLM sees the DDL.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.prompts.enrichment import (
    format_enrichment_table_block,
    render_enrichment_prompt,
)
from src.agent.utils import extract_json, message_text
from src.config.settings import get_settings
from src.context.schema_enrichment import SchemaEnrichmentStore
from src.context.schema_linker import SchemaLinker
from src.providers.llm import get_llm_provider
from src.storage.database import async_session_factory
from src.storage.models import SchemaCache

logger = logging.getLogger(__name__)

ProgressCallback = Callable[..., None]

# Rebuild FAISS once after enrichment (not every batch) — cheaper embeddings.
_DDL_HASH_PREFIX = "ddl:"

# Boilerplate columns that add tokens but little retrieval signal.
_TRIVIAL_COLS = frozenset(
    {
        "id",
        "active",
        "create_uid",
        "write_uid",
        "create_date",
        "write_date",
        "created_at",
        "updated_at",
        "__last_update",
    }
)


def _safe_json_loads(raw: Optional[str], default: Any = None) -> Any:
    if raw is None or raw == "":
        return default if default is not None else None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else None


def _ddl_hash(cache: SchemaCache) -> str:
    """Stable short hash of table name + column schema for change detection."""
    payload = f"{cache.table_name}\n{cache.columns_json or ''}"
    digest = hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]
    return f"{_DDL_HASH_PREFIX}{digest}"


def _is_trivial_column(name: str) -> bool:
    lower = (name or "").strip().lower()
    if not lower:
        return True
    if lower in _TRIVIAL_COLS:
        return True
    # FK / audit id columns — relationships already appear in DDL FK lines.
    if lower.endswith("_id") or lower.endswith("_uid"):
        return True
    return False


def _build_create_table_statement(
    cache: SchemaCache,
    *,
    skip_trivial: bool = True,
) -> str:
    columns = _safe_json_loads(cache.columns_json, default=[]) or []
    lines: list[str] = []
    for col in columns:
        name = col.get("name") or col.get("column_name")
        if not name:
            continue
        if skip_trivial and _is_trivial_column(str(name)):
            continue
        col_type = col.get("type") or col.get("data_type") or "UNKNOWN"
        parts = [f"  {name} {col_type}"]
        if col.get("primary_key"):
            parts.append("PRIMARY KEY")
        if col.get("nullable") is False and not col.get("primary_key"):
            parts.append("NOT NULL")
        fk = col.get("foreign_key")
        if isinstance(fk, dict):
            ft = fk.get("table") or fk.get("foreign_table_name")
            fc = fk.get("column") or fk.get("foreign_column_name")
            if ft and fc:
                parts.append(f"REFERENCES {ft}({fc})")
        lines.append(" ".join(parts))
    body = ",\n".join(lines) if lines else "  -- (no non-trivial columns)"
    return f"CREATE TABLE {cache.table_name} (\n{body}\n);"


def _sample_rows_text(cache: SchemaCache, limit: int = 3) -> str:
    rows = _safe_json_loads(cache.sample_rows_json, default=[]) or []
    if not rows:
        return "(no sample rows)"
    # Drop trivial keys from samples to save tokens.
    trimmed: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        trimmed.append(
            {
                k: v
                for k, v in row.items()
                if not _is_trivial_column(str(k))
            }
        )
    try:
        return json.dumps(trimmed or rows[:limit], default=str)
    except TypeError:
        return str(trimmed or rows[:limit])


def _chunked(items: list[SchemaCache], size: int) -> list[list[SchemaCache]]:
    if size <= 0:
        size = 1
    return [items[i : i + size] for i in range(0, len(items), size)]


class SchemaAutoEnricher:
    """LLM-backed enrichment of schema cache into SchemaEnrichmentStore."""

    def __init__(self) -> None:
        self.store = SchemaEnrichmentStore()
        self._settings = get_settings()

    async def enrich_connection(
        self,
        session: AsyncSession,
        connection_id: str,
        caches: list[SchemaCache],
        *,
        progress: Optional[ProgressCallback] = None,
        skip_existing: bool = True,
    ) -> int:
        """Enrich tables in parallel batches. Returns tables successfully enriched."""

        def _progress(**kwargs: Any) -> None:
            if progress is not None:
                progress(**kwargs)

        if not caches:
            _progress(
                phase="enriching",
                message="No tables to enrich",
                current_table=None,
                tables_total=0,
                tables_done=0,
            )
            return 0

        existing_hash: dict[str, str] = {}
        if skip_existing:
            rows = await self.store.list(session, connection_id)
            for row in rows:
                if row.column_name is not None:
                    continue
                alias = (row.alias or "").strip()
                if alias.startswith(_DDL_HASH_PREFIX):
                    existing_hash[row.table_name] = alias
                elif row.description:
                    # Legacy enrichment without hash — keep until DDL hash forces refresh.
                    existing_hash[row.table_name] = ""

        to_enrich: list[SchemaCache] = []
        for cache in caches:
            wanted = _ddl_hash(cache)
            prior = existing_hash.get(cache.table_name)
            if skip_existing and prior == wanted:
                continue
            # Missing or mismatched hash (including legacy rows) → enrich / stamp hash.
            to_enrich.append(cache)

        total = len(to_enrich)
        if total == 0:
            _progress(
                phase="enriching",
                message="Schema descriptions already current",
                current_table=None,
                tables_total=len(caches),
                tables_done=len(caches),
            )
            return 0

        batch_size = int(self._settings.enrichment_batch_size)
        concurrency = int(self._settings.enrichment_concurrency)
        batches = _chunked(to_enrich, batch_size)

        _progress(
            phase="enriching",
            message=(
                f"Enriching {total} tables in {len(batches)} batch(es) "
                f"(size={batch_size}, concurrency={concurrency})"
            ),
            current_table=None,
            tables_total=total,
            tables_done=0,
        )

        semaphore = asyncio.Semaphore(max(1, concurrency))
        done_count = 0
        enriched_total = 0
        lock = asyncio.Lock()

        async def _run_batch(batch: list[SchemaCache], batch_index: int) -> int:
            nonlocal done_count, enriched_total
            async with semaphore:
                names = ", ".join(c.table_name for c in batch)
                _progress(
                    phase="enriching",
                    message=f"Enriching batch {batch_index + 1}/{len(batches)}: {names}",
                    current_table=batch[0].table_name if batch else None,
                    tables_total=total,
                    tables_done=done_count,
                )
                count = 0
                try:
                    # Own session per batch — AsyncSession is not concurrency-safe.
                    async with async_session_factory() as batch_session:
                        count = await self._enrich_batch(
                            batch_session, connection_id, batch
                        )
                except Exception:
                    logger.exception(
                        "Auto-enrich batch failed for %s (%s)",
                        connection_id,
                        names,
                    )
                    count = 0

                async with lock:
                    done_count += len(batch)
                    enriched_total += count
                    current_done = done_count
                    current_enriched = enriched_total

                _progress(
                    phase="enriching",
                    message=(
                        f"Finished batch {batch_index + 1}/{len(batches)} "
                        f"({current_enriched} enriched so far)"
                    ),
                    current_table=batch[-1].table_name if batch else None,
                    tables_total=total,
                    tables_done=current_done,
                    table_just_done=batch[-1].table_name if batch else None,
                )
                return count

        await asyncio.gather(
            *[_run_batch(batch, i) for i, batch in enumerate(batches)]
        )

        if enriched_total > 0:
            try:
                # Use caller session for final index rebuild.
                await SchemaLinker().build_table_index(session, connection_id)
            except Exception:
                logger.exception(
                    "FAISS rebuild failed for %s after enrich",
                    connection_id,
                )

        _progress(
            phase="enriching",
            message=f"Enriched {enriched_total}/{total} tables",
            current_table=None,
            tables_total=total,
            tables_done=total,
        )
        return enriched_total

    async def _enrich_batch(
        self,
        session: AsyncSession,
        connection_id: str,
        batch: list[SchemaCache],
    ) -> int:
        if not batch:
            return 0

        blocks: list[str] = []
        for index, cache in enumerate(batch, start=1):
            blocks.append(
                format_enrichment_table_block(
                    cache.table_name,
                    _build_create_table_statement(cache, skip_trivial=True),
                    _sample_rows_text(cache),
                    index=index,
                )
            )
        system = render_enrichment_prompt(tables_block="\n\n".join(blocks))
        model = (self._settings.enrichment_model or "").strip() or None
        llm = get_llm_provider().get_chat_model(
            temperature=0.2,
            max_tokens=int(self._settings.enrichment_max_tokens),
            model=model,
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(content="Return JSON only."),
            ]
        )
        parsed = extract_json(message_text(response))
        if not isinstance(parsed, dict):
            return 0

        enriched = 0
        known = {c.table_name: c for c in batch}
        for table_name, cache in known.items():
            payload = parsed.get(table_name)
            # Tolerate nested {"tables": {...}} wrappers from some models.
            if payload is None and isinstance(parsed.get("tables"), dict):
                payload = parsed["tables"].get(table_name)
            if not isinstance(payload, dict):
                # Single-table legacy response shape.
                if len(batch) == 1 and (
                    "table_description" in parsed or "columns" in parsed
                ):
                    payload = parsed
                else:
                    continue

            ok = await self._persist_table_enrichment(
                session,
                connection_id,
                cache,
                payload,
            )
            if ok:
                enriched += 1

        if enriched > 0:
            await session.commit()
        return enriched

    async def _persist_table_enrichment(
        self,
        session: AsyncSession,
        connection_id: str,
        cache: SchemaCache,
        payload: dict[str, Any],
    ) -> bool:
        table_description = (
            str(payload.get("table_description") or "").strip() or None
        )
        columns = payload.get("columns") or {}
        if not isinstance(columns, dict):
            columns = {}

        ddl_hash = _ddl_hash(cache)
        await self.store.upsert(
            session,
            connection_id=connection_id,
            table_name=cache.table_name,
            column_name=None,
            description=table_description,
            alias=ddl_hash,
        )

        for col_name, description in columns.items():
            name = str(col_name).strip()
            if not name or _is_trivial_column(name):
                continue
            desc = str(description).strip() if description is not None else ""
            await self.store.upsert(
                session,
                connection_id=connection_id,
                table_name=cache.table_name,
                column_name=name,
                description=desc or None,
            )
        return True


# Backwards-compatible alias
AutoEnricher = SchemaAutoEnricher
