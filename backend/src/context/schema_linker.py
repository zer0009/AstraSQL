from __future__ import annotations

import asyncio
import json
import pickle
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

import faiss
import numpy as np
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.prompts.schema_link import (
    render_column_first_prompt,
    render_table_first_prompt,
)
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider
from src.storage.models import SchemaCache, SchemaEnrichment


def extract_json(text: str) -> Any:
    """Parse JSON from an LLM response, stripping markdown fences if present."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", cleaned)
        if match:
            return json.loads(match.group(0))
        raise


def _normalize(vectors: np.ndarray) -> np.ndarray:
    faiss.normalize_L2(vectors)
    return vectors


def _extract_sample_values(
    sample_rows_json: str | None,
    *,
    max_cols: int = 5,
    max_values_per_col: int = 3,
) -> str:
    """Build a short 'Sample data' snippet from cached sample rows for embeddings."""
    if not sample_rows_json:
        return ""
    try:
        rows = json.loads(sample_rows_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(rows, list) or not rows:
        return ""

    # Collect distinct string-ish values per column (skip pure ids / nulls).
    by_col: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if value is None:
                continue
            key_l = str(key).lower()
            if key_l == "id" or key_l.endswith("_id"):
                continue
            text = str(value).strip()
            if not text or len(text) > 80:
                continue
            bucket = by_col.setdefault(str(key), [])
            if text not in bucket and len(bucket) < max_values_per_col:
                bucket.append(text)

    parts: list[str] = []
    for col_name, values in list(by_col.items())[:max_cols]:
        if values:
            parts.append(f"{col_name}=[{', '.join(values)}]")
    return "; ".join(parts)


class SchemaLinker:
    """Two-phase schema linker: FAISS coarse filter → LLM bidirectional fine select."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def _index_path(self, connection_id: str) -> Path:
        return self._settings.faiss_dir / f"{connection_id}_tables.index"

    def _ids_path(self, connection_id: str) -> Path:
        return self._settings.faiss_dir / f"{connection_id}_tables_ids.pkl"

    def _ensure_faiss_dir(self) -> None:
        self._settings.faiss_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(
        self, connection_id: str
    ) -> tuple[Optional[faiss.Index], list[str]]:
        index_path = self._index_path(connection_id)
        ids_path = self._ids_path(connection_id)
        if not index_path.exists() or not ids_path.exists():
            return None, []
        try:
            index = faiss.read_index(str(index_path))
            with open(ids_path, "rb") as f:
                names: list[str] = pickle.load(f)
            return index, names
        except Exception:
            return None, []

    def _save_index(
        self, connection_id: str, index: faiss.Index, names: list[str]
    ) -> None:
        self._ensure_faiss_dir()
        faiss.write_index(index, str(self._index_path(connection_id)))
        with open(self._ids_path(connection_id), "wb") as f:
            pickle.dump(names, f)

    async def _embed_texts(self, texts: list[str]) -> np.ndarray:
        embeddings = get_llm_provider().get_embedding_model()
        if hasattr(embeddings, "aembed_documents"):
            vecs = await embeddings.aembed_documents(texts)
        else:
            vecs = embeddings.embed_documents(texts)
        mat = np.asarray(vecs, dtype=np.float32)
        return _normalize(mat)

    async def _embed_query(self, text: str) -> np.ndarray:
        embeddings = get_llm_provider().get_embedding_model()
        if hasattr(embeddings, "aembed_query"):
            vec = await embeddings.aembed_query(text)
        else:
            vec = embeddings.embed_query(text)
        arr = np.asarray(vec, dtype=np.float32).reshape(1, -1)
        return _normalize(arr)

    async def build_table_index(
        self, session: AsyncSession, connection_id: str
    ) -> int:
        """Build FAISS index of table descriptions from SchemaCache + enrichments."""
        cache_result = await session.execute(
            select(SchemaCache).where(SchemaCache.connection_id == connection_id)
        )
        caches = list(cache_result.scalars().all())

        enrich_result = await session.execute(
            select(SchemaEnrichment).where(
                SchemaEnrichment.connection_id == connection_id,
                SchemaEnrichment.column_name.is_(None),
            )
        )
        table_desc: dict[str, str] = {}
        for e in enrich_result.scalars().all():
            text = (e.description or "").strip()
            if not text:
                alias = (e.alias or "").strip()
                if alias and not alias.startswith("ddl:"):
                    text = alias
            table_desc[e.table_name] = text

        # Column-level enrichments for richer embedding text.
        col_enrich_result = await session.execute(
            select(SchemaEnrichment).where(
                SchemaEnrichment.connection_id == connection_id,
                SchemaEnrichment.column_name.is_not(None),
            )
        )
        col_desc: dict[str, dict[str, str]] = {}
        for e in col_enrich_result.scalars().all():
            if not e.column_name:
                continue
            col_desc.setdefault(e.table_name, {})[e.column_name] = (
                e.description or e.alias or ""
            )

        if not caches:
            index_path = self._index_path(connection_id)
            ids_path = self._ids_path(connection_id)
            if index_path.exists():
                index_path.unlink()
            if ids_path.exists():
                ids_path.unlink()
            return 0

        texts: list[str] = []
        names: list[str] = []
        for cache in caches:
            name = cache.table_name
            desc = table_desc.get(name, "")
            try:
                columns = json.loads(cache.columns_json) if cache.columns_json else []
            except (json.JSONDecodeError, TypeError):
                columns = []

            col_details: list[str] = []
            table_col_meta = col_desc.get(name, {})
            for c in columns:
                col_name = c.get("name") or c.get("column_name") or ""
                if not col_name:
                    continue
                detail = str(col_name)
                c_desc = (
                    table_col_meta.get(col_name)
                    or c.get("description")
                    or ""
                )
                if c_desc:
                    detail += f" ({c_desc})"
                col_details.append(detail)

            text = f"{name}: {desc}".strip()
            if col_details:
                text = f"{text}. Columns: {', '.join(col_details)}"
            sample_vals = _extract_sample_values(cache.sample_rows_json)
            if sample_vals:
                text = f"{text}. Sample data: {sample_vals}"
            texts.append(text)
            names.append(name)

        mat = await self._embed_texts(texts)
        index = faiss.IndexFlatIP(mat.shape[1])
        index.add(mat)
        self._save_index(connection_id, index, names)
        return len(names)

    async def coarse_filter(
        self,
        connection_id: str,
        question: str,
        all_tables: list[str],
        top_k: Optional[int] = None,
    ) -> list[str]:
        """Phase 1: FAISS coarse filter. Skip if fewer than 20 tables."""
        if top_k is None:
            top_k = self._settings.faiss_top_k_tables

        if len(all_tables) < 20:
            return list(all_tables)

        index, names = self._load_index(connection_id)
        if index is None or index.ntotal == 0 or not names:
            return list(all_tables)[:top_k]

        k = min(top_k, index.ntotal, len(names))
        if k <= 0:
            return list(all_tables)[:top_k]

        query = await self._embed_query(question)
        _, indices = index.search(query, k)

        selected: list[str] = []
        all_set = set(all_tables)
        for idx in indices[0]:
            if idx < 0 or idx >= len(names):
                continue
            name = names[idx]
            if name in all_set and name not in selected:
                selected.append(name)

        # Preserve any tables in all_tables that somehow weren't indexed
        if not selected:
            return list(all_tables)[:top_k]
        return selected

    async def fine_select(
        self,
        question: str,
        candidate_tables: list[dict[str, Any]],
        conversation_history: str = "",
    ) -> dict[str, Any]:
        """Phase 2: parallel table-first + column-first LLM calls, union merge.

        Returns ``{"tables": [...], "columns": [{"table", "column"}, ...]}``.
        """
        if not candidate_tables:
            return {"tables": [], "columns": []}

        table_catalog_lines: list[str] = []
        compact_lines: list[str] = []
        known_tables: set[str] = set()

        for t in candidate_tables:
            name = t.get("name") or t.get("table_name") or ""
            if not name:
                continue
            known_tables.add(name)
            desc = t.get("description") or ""
            table_catalog_lines.append(f"{name}: {desc}" if desc else f"{name}:")

            columns = t.get("columns") or []
            for col in columns:
                col_name = col.get("name") or col.get("column_name") or ""
                if not col_name:
                    continue
                col_type = col.get("type") or col.get("data_type") or ""
                col_desc = col.get("description") or ""
                line = f"{name}.{col_name}"
                if col_type:
                    line += f" ({col_type})"
                if col_desc:
                    line += f" [{col_desc}]"
                fk = col.get("foreign_key")
                if isinstance(fk, dict):
                    fk_table = fk.get("table") or fk.get("foreign_table_name")
                    fk_col = fk.get("column") or fk.get("foreign_column_name")
                    if fk_table and fk_col:
                        line += f" FK→{fk_table}.{fk_col}"
                    elif fk_table:
                        line += f" FK→{fk_table}"
                compact_lines.append(line)

        current_date = date.today().isoformat()
        table_system, table_user = render_table_first_prompt(
            user_question=question,
            table_catalog="\n".join(table_catalog_lines),
            current_date=current_date,
            conversation_history=conversation_history,
        )
        col_system, col_user = render_column_first_prompt(
            user_question=question,
            compact_schema="\n".join(compact_lines),
            current_date=current_date,
            conversation_history=conversation_history,
        )

        chat = get_llm_provider().get_chat_model(temperature=0.0)

        async def _call(system: str, user: str) -> str:
            resp = await chat.ainvoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
            content = resp.content
            if isinstance(content, list):
                return "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            return str(content)

        table_raw, col_raw = await asyncio.gather(
            _call(table_system, table_user),
            _call(col_system, col_user),
        )

        tables: set[str] = set()
        columns: list[dict[str, str]] = []
        seen_cols: set[tuple[str, str]] = set()

        try:
            table_data = extract_json(table_raw)
            for name in table_data.get("selected_tables") or []:
                if isinstance(name, str) and name in known_tables:
                    tables.add(name)
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

        try:
            col_data = extract_json(col_raw)
            for item in col_data.get("selected_columns") or []:
                if not isinstance(item, dict):
                    continue
                t_name = item.get("table")
                c_name = item.get("column")
                if not t_name or not c_name:
                    continue
                if t_name not in known_tables:
                    continue
                tables.add(t_name)
                key = (t_name, c_name)
                if key not in seen_cols:
                    seen_cols.add(key)
                    columns.append({"table": t_name, "column": c_name})
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

        # Fallback: if LLM returned nothing usable, keep all candidates
        if not tables:
            tables = set(known_tables)

        return {"tables": sorted(tables), "columns": columns}
