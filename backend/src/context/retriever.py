from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import sqlglot
from sqlglot import exp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.context.business_rules import BusinessRulesStore
from src.context.golden_records import GoldenRecordsStore
from src.context.schema_enrichment import SchemaEnrichmentStore
from src.context.schema_linker import SchemaLinker
from src.providers.database.base import BaseDatabaseProvider
from src.storage.models import Connection, SchemaCache

# Cap how many FK-neighbor tables we add after fine_select.
_FK_EXPAND_MAX_EXTRA = 10
# How many prior turns to fold into the FAISS / linker query text.
_LINK_HISTORY_TURNS = 3
# Generic column-name hints that a table is a human-label / lookup table.
_LABEL_COLUMN_NAMES = frozenset(
    {"name", "title", "label", "code", "display_name", "displayname"}
)


def _column_names(cache: SchemaCache | None) -> set[str]:
    if cache is None:
        return set()
    columns = _safe_json_loads(cache.columns_json, default=[]) or []
    names: set[str] = set()
    for col in columns:
        if not isinstance(col, dict):
            continue
        raw = col.get("name") or col.get("column_name")
        if raw:
            names.add(str(raw).lower())
    return names


def _is_label_table(cache: SchemaCache | None) -> bool:
    """True if the table has common human-readable label columns (metadata only)."""
    return bool(_column_names(cache) & _LABEL_COLUMN_NAMES)


def _fk_targets_from_tables(
    source_tables: list[str],
    cache_by_name: dict[str, SchemaCache],
    *,
    exclude: set[str],
) -> list[str]:
    """Collect unique FK target table names from the given sources (order preserved)."""
    known = set(cache_by_name.keys())
    found: list[str] = []
    seen: set[str] = set(exclude)

    for name in source_tables:
        cache = cache_by_name.get(name)
        if cache is None:
            continue
        columns = _safe_json_loads(cache.columns_json, default=[]) or []
        for col in columns:
            if not isinstance(col, dict):
                continue
            fk = col.get("foreign_key")
            if not isinstance(fk, dict):
                continue
            target = fk.get("table") or fk.get("foreign_table_name")
            if (
                isinstance(target, str)
                and target in known
                and target not in seen
            ):
                seen.add(target)
                found.append(target)
    return found


def _rank_fk_candidates(
    candidates: list[str],
    cache_by_name: dict[str, SchemaCache],
) -> list[str]:
    """Prefer label-like lookup tables when the expansion cap is tight."""
    return sorted(
        candidates,
        key=lambda t: (0 if _is_label_table(cache_by_name.get(t)) else 1, t),
    )


def _expand_fk_targets(
    selected_tables: list[str],
    cache_by_name: dict[str, SchemaCache],
    *,
    max_extra: int = _FK_EXPAND_MAX_EXTRA,
) -> list[str]:
    """Add FK neighbor tables (2 passes, capped) using SchemaCache metadata only.

    Pass A: FK targets of the selected set (ranked: label tables first).
    Pass B: FK targets of tables added in pass A (same ranking), so lookup
    chains like entity → dimension resolve without hardcoded table names.

    A few slots are reserved for pass B so high-degree fact tables cannot
    consume the entire cap before dimension lookups are considered.
    """
    if not selected_tables or max_extra <= 0:
        return list(selected_tables)

    ordered = list(selected_tables)
    selected_set = set(ordered)
    # Keep room for a second hop (e.g. partner → country/state).
    reserve_b = min(3, max_extra // 2) if max_extra >= 2 else 0
    pass_a_budget = max_extra - reserve_b
    remaining = max_extra

    pass_a = _rank_fk_candidates(
        _fk_targets_from_tables(ordered, cache_by_name, exclude=selected_set),
        cache_by_name,
    )
    newly_added: list[str] = []
    pass_a_leftover: list[str] = []

    for target in pass_a:
        if len(newly_added) >= pass_a_budget:
            pass_a_leftover.append(target)
            continue
        if target in selected_set:
            continue
        selected_set.add(target)
        ordered.append(target)
        newly_added.append(target)
        remaining -= 1

    if newly_added and remaining > 0:
        pass_b = _rank_fk_candidates(
            _fk_targets_from_tables(
                newly_added, cache_by_name, exclude=selected_set
            ),
            cache_by_name,
        )
        for target in pass_b:
            if remaining <= 0:
                break
            if target in selected_set:
                continue
            selected_set.add(target)
            ordered.append(target)
            remaining -= 1

    # Fill any leftover budget with unused pass-A candidates.
    for target in pass_a_leftover:
        if remaining <= 0:
            break
        if target in selected_set:
            continue
        selected_set.add(target)
        ordered.append(target)
        remaining -= 1

    return ordered


@dataclass
class RetrievedContext:
    enriched_schema: str
    business_rules: str
    golden_records_text: str
    selected_tables: list[str]
    selected_columns: list[dict]
    used_golden: bool = False
    steps: list[dict] = field(default_factory=list)


def _safe_json_loads(raw: Optional[str], default: Any = None) -> Any:
    if raw is None or raw == "":
        return default if default is not None else None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else None


def _tables_from_sql(sql: str | None) -> list[str]:
    """Extract table names from SQL via sqlglot AST (dialect-agnostic best-effort)."""
    text = (sql or "").strip()
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    try:
        for tree in sqlglot.parse(text):
            if tree is None:
                continue
            for table in tree.find_all(exp.Table):
                name = table.name
                if name and name not in seen:
                    seen.add(name)
                    found.append(name)
    except Exception:
        return []
    return found


def _prior_tables_from_history(
    conversation_history: list[dict[str, Any]] | None,
    known_tables: set[str],
) -> list[str]:
    """Union of tables referenced in prior-turn SQL that exist in SchemaCache."""
    if not conversation_history:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for turn in conversation_history:
        if not isinstance(turn, dict):
            continue
        for name in _tables_from_sql(str(turn.get("sql") or "")):
            if name in known_tables and name not in seen:
                seen.add(name)
                found.append(name)
    return found


def _build_link_query(
    question: str,
    conversation_history: list[dict[str, Any]] | None,
    *,
    max_turns: int = _LINK_HISTORY_TURNS,
) -> str:
    """FAISS / linker query: current question + recent prior questions/answers."""
    parts: list[str] = [question.strip()] if question and question.strip() else []
    if conversation_history:
        for turn in conversation_history[-max_turns:]:
            if not isinstance(turn, dict):
                continue
            prior_q = str(turn.get("question") or "").strip()
            prior_a = str(turn.get("answer") or "").strip()
            if prior_q:
                parts.append(prior_q)
            if prior_a:
                # Keep answer snippets short so embedding stays focused.
                parts.append(prior_a[:200])
    return "\n".join(parts) if parts else question


def _format_history_for_linker(
    conversation_history: list[dict[str, Any]] | None,
    *,
    max_turns: int = _LINK_HISTORY_TURNS,
) -> str:
    """Compact history text for schema-link LLM prompts."""
    if not conversation_history:
        return ""
    blocks: list[str] = []
    for index, turn in enumerate(conversation_history[-max_turns:], start=1):
        if not isinstance(turn, dict):
            continue
        q = str(turn.get("question") or "").strip()
        if not q:
            continue
        a = str(turn.get("answer") or "").strip()
        line = f"Turn {index} — User: {q}"
        if a:
            line += f"\n  Answer: {a[:180]}"
        blocks.append(line)
    return "\n".join(blocks)


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
        conversation_history: list[dict[str, Any]] | None = None,
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
        known_tables = set(all_table_names)

        # 2. SchemaLinker coarse + fine (history-aware)
        link_query = _build_link_query(question, conversation_history)
        history_text = _format_history_for_linker(conversation_history)
        prior_tables = _prior_tables_from_history(
            conversation_history, known_tables
        )

        candidates = await self.linker.coarse_filter(
            connection_id,
            link_query,
            all_table_names,
            top_k=self._settings.faiss_top_k_tables,
        )
        # Keep prior-turn fact tables even if FAISS dropped them this turn.
        for name in prior_tables:
            if name not in candidates:
                candidates.append(name)

        steps.append(
            {
                "step": "schema_coarse",
                "detail": (
                    f"Coarse filter selected {len(candidates)} of "
                    f"{len(all_table_names)} tables"
                    + (
                        f" (+{len(prior_tables)} from prior SQL)"
                        if prior_tables
                        else ""
                    )
                ),
                "tables": candidates,
                "prior_tables": prior_tables,
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

        fine = await self.linker.fine_select(
            question,
            candidate_payload,
            conversation_history=history_text,
        )
        selected_tables: list[str] = fine.get("tables") or []
        selected_columns: list[dict] = fine.get("columns") or []

        # Union prior SQL tables into the fine-selected set before FK expand.
        for name in prior_tables:
            if name not in selected_tables:
                selected_tables.append(name)

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

        before_expand = list(selected_tables)
        selected_tables = _expand_fk_targets(
            selected_tables,
            cache_by_name,
            max_extra=_FK_EXPAND_MAX_EXTRA,
        )
        added_fk = [t for t in selected_tables if t not in before_expand]
        if added_fk:
            steps.append(
                {
                    "step": "schema_fk_expand",
                    "detail": (
                        f"Added {len(added_fk)} FK neighbor table(s) "
                        f"(2-pass, label-preferring, cap {_FK_EXPAND_MAX_EXTRA})"
                    ),
                    "tables": added_fk,
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
        used_golden = len(golden_hits) > 0
        steps.append(
            {
                "step": "golden_records",
                "detail": f"Retrieved {len(golden_hits)} similar golden records",
                "used_golden": used_golden,
            }
        )

        return RetrievedContext(
            enriched_schema=enriched_schema,
            business_rules=business_rules,
            golden_records_text=golden_records_text,
            selected_tables=selected_tables,
            selected_columns=selected_columns,
            used_golden=used_golden,
            steps=steps,
        )
