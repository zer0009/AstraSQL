"""Auto-generate table/column descriptions after a schema scan."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.prompts.enrichment import render_enrichment_prompt
from src.agent.utils import extract_json, message_text
from src.config.settings import get_settings
from src.context.schema_enrichment import SchemaEnrichmentStore
from src.context.schema_linker import SchemaLinker
from src.providers.llm import get_llm_provider
from src.storage.models import SchemaCache

logger = logging.getLogger(__name__)

ProgressCallback = Callable[..., None]

# Rebuild FAISS every N committed tables so partial progress stays searchable.
_FAISS_REBUILD_EVERY = 20


def _safe_json_loads(raw: Optional[str], default: Any = None) -> Any:
    if raw is None or raw == "":
        return default if default is not None else None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else None


def _build_create_table_statement(cache: SchemaCache) -> str:
    columns = _safe_json_loads(cache.columns_json, default=[]) or []
    if cache.ddl_text and cache.ddl_text.strip():
        return cache.ddl_text.strip()

    lines: list[str] = []
    for col in columns:
        name = col.get("name") or col.get("column_name")
        if not name:
            continue
        col_type = col.get("type") or col.get("data_type") or "UNKNOWN"
        parts = [f"  {name} {col_type}"]
        if col.get("primary_key"):
            parts.append("PRIMARY KEY")
        if col.get("nullable") is False and not col.get("primary_key"):
            parts.append("NOT NULL")
        lines.append(" ".join(parts))
    body = ",\n".join(lines) if lines else "  -- (no columns)"
    return f"CREATE TABLE {cache.table_name} (\n{body}\n);"


def _sample_rows_text(cache: SchemaCache, limit: int = 5) -> str:
    rows = _safe_json_loads(cache.sample_rows_json, default=[]) or []
    if not rows:
        return "(no sample rows)"
    try:
        return json.dumps(rows[:limit], default=str, indent=2)
    except TypeError:
        return str(rows[:limit])


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
        """Enrich tables one-by-one. Returns number of tables successfully enriched."""

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

        existing: set[str] = set()
        if skip_existing:
            rows = await self.store.list(session, connection_id)
            for row in rows:
                if row.column_name is None and row.description:
                    existing.add(row.table_name)

        to_enrich = [c for c in caches if c.table_name not in existing]
        total = len(to_enrich)
        if total == 0:
            _progress(
                phase="enriching",
                message="Schema descriptions already present",
                current_table=None,
                tables_total=len(caches),
                tables_done=len(caches),
            )
            return 0

        enriched = 0
        linker = SchemaLinker()
        for i, cache in enumerate(to_enrich):
            _progress(
                phase="enriching",
                message=f"Enriching descriptions {i + 1}/{total}: {cache.table_name}",
                current_table=cache.table_name,
                tables_total=total,
                tables_done=i,
            )
            try:
                ok = await self._enrich_table(session, connection_id, cache)
                if ok:
                    enriched += 1
                    # Keep FAISS within N tables of reality during long runs.
                    if enriched % _FAISS_REBUILD_EVERY == 0:
                        try:
                            await linker.build_table_index(session, connection_id)
                        except Exception:
                            logger.exception(
                                "Periodic FAISS rebuild failed for %s after %s tables",
                                connection_id,
                                enriched,
                            )
            except Exception:
                logger.exception(
                    "Auto-enrich failed for %s.%s",
                    connection_id,
                    cache.table_name,
                )
                try:
                    await session.rollback()
                except Exception:
                    logger.exception(
                        "Rollback failed after enrich error for %s.%s",
                        connection_id,
                        cache.table_name,
                    )
            _progress(
                phase="enriching",
                message=f"Enriched {i + 1}/{total}: {cache.table_name}",
                current_table=cache.table_name,
                tables_total=total,
                tables_done=i + 1,
                table_just_done=cache.table_name,
            )

        if enriched > 0 and enriched % _FAISS_REBUILD_EVERY != 0:
            try:
                await linker.build_table_index(session, connection_id)
            except Exception:
                logger.exception(
                    "Final FAISS rebuild failed for %s after enrich",
                    connection_id,
                )

        _progress(
            phase="enriching",
            message=f"Enriched {enriched}/{total} tables",
            current_table=None,
            tables_total=total,
            tables_done=total,
        )
        return enriched

    async def _enrich_table(
        self,
        session: AsyncSession,
        connection_id: str,
        cache: SchemaCache,
    ) -> bool:
        ddl = _build_create_table_statement(cache)
        samples = _sample_rows_text(cache)
        system = render_enrichment_prompt(ddl, samples)
        llm = get_llm_provider().get_chat_model(
            temperature=0.2,
            max_tokens=self._settings.llm_max_tokens,
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(content="Return JSON only."),
            ]
        )
        parsed = extract_json(message_text(response))
        if not isinstance(parsed, dict):
            return False

        table_description = str(parsed.get("table_description") or "").strip() or None
        columns = parsed.get("columns") or {}
        if not isinstance(columns, dict):
            columns = {}

        await self.store.upsert(
            session,
            connection_id=connection_id,
            table_name=cache.table_name,
            column_name=None,
            description=table_description,
        )

        for col_name, description in columns.items():
            name = str(col_name).strip()
            if not name:
                continue
            desc = str(description).strip() if description is not None else ""
            await self.store.upsert(
                session,
                connection_id=connection_id,
                table_name=cache.table_name,
                column_name=name,
                description=desc or None,
            )
        # Short transaction per table so chat/history writers are not blocked
        # for the duration of a multi-hundred-table enrich run.
        await session.commit()
        return True


# Backwards-compatible alias
AutoEnricher = SchemaAutoEnricher
