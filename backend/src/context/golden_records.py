from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any, Optional

import faiss
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.providers.llm import get_llm_provider
from src.storage.models import GoldenRecord


def _embed_to_bytes(vec: list[float] | np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _bytes_to_embed(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32).copy()


def _normalize(vectors: np.ndarray) -> np.ndarray:
    faiss.normalize_L2(vectors)
    return vectors


class GoldenRecordsStore:
    """NL→SQL exemplar bank: SQLite rows + per-connection FAISS index."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def _index_path(self, connection_id: str) -> Path:
        return self._settings.faiss_dir / f"{connection_id}_golden.index"

    def _ids_path(self, connection_id: str) -> Path:
        return self._settings.faiss_dir / f"{connection_id}_golden_ids.pkl"

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
                ids: list[str] = pickle.load(f)
            return index, ids
        except Exception:
            return None, []

    def _save_index(
        self, connection_id: str, index: faiss.Index, ids: list[str]
    ) -> None:
        self._ensure_faiss_dir()
        faiss.write_index(index, str(self._index_path(connection_id)))
        with open(self._ids_path(connection_id), "wb") as f:
            pickle.dump(ids, f)

    async def _embed_text(self, text: str) -> np.ndarray:
        embeddings = get_llm_provider().get_embedding_model()
        if hasattr(embeddings, "aembed_query"):
            vec = await embeddings.aembed_query(text)
        else:
            vec = embeddings.embed_query(text)
        arr = np.asarray(vec, dtype=np.float32).reshape(1, -1)
        return _normalize(arr)

    async def add(
        self,
        session: AsyncSession,
        connection_id: str,
        question: str,
        sql: str,
    ) -> GoldenRecord:
        vec = await self._embed_text(question)
        row = GoldenRecord(
            connection_id=connection_id,
            question=question,
            sql=sql,
            embedding=_embed_to_bytes(vec.reshape(-1)),
        )
        session.add(row)
        await session.flush()

        index, ids = self._load_index(connection_id)
        if index is None or index.ntotal == 0:
            index = faiss.IndexFlatIP(vec.shape[1])
            ids = []
        index.add(vec)
        ids.append(row.id)
        self._save_index(connection_id, index, ids)
        return row

    async def delete(self, session: AsyncSession, id: str) -> bool:
        row = await session.get(GoldenRecord, id)
        if row is None:
            return False
        connection_id = row.connection_id
        await session.delete(row)
        await session.flush()
        await self.rebuild_index(session, connection_id)
        return True

    async def list(
        self, session: AsyncSession, connection_id: str
    ) -> list[GoldenRecord]:
        result = await session.execute(
            select(GoldenRecord)
            .where(GoldenRecord.connection_id == connection_id)
            .order_by(GoldenRecord.created_at.desc())
        )
        return list(result.scalars().all())

    async def search(
        self,
        session: AsyncSession,
        connection_id: str,
        question: str,
        top_k: Optional[int] = None,
    ) -> list[dict[str, str]]:
        if top_k is None:
            top_k = self._settings.golden_records_top_k

        index, ids = self._load_index(connection_id)
        if index is None or index.ntotal == 0 or not ids:
            return []

        k = min(top_k, index.ntotal, len(ids))
        if k <= 0:
            return []

        query = await self._embed_text(question)
        scores, indices = index.search(query, k)

        out: list[dict[str, str]] = []
        for idx in indices[0]:
            if idx < 0 or idx >= len(ids):
                continue
            record_id = ids[idx]
            row = await session.get(GoldenRecord, record_id)
            if row is None:
                continue
            out.append({"question": row.question, "sql": row.sql})
        return out

    async def rebuild_index(
        self, session: AsyncSession, connection_id: str
    ) -> int:
        """Rebuild FAISS from all DB rows for this connection. Returns vector count."""
        result = await session.execute(
            select(GoldenRecord).where(GoldenRecord.connection_id == connection_id)
        )
        rows = list(result.scalars().all())

        index_path = self._index_path(connection_id)
        ids_path = self._ids_path(connection_id)

        if not rows:
            if index_path.exists():
                index_path.unlink()
            if ids_path.exists():
                ids_path.unlink()
            return 0

        vectors: list[np.ndarray] = []
        ids: list[str] = []
        embeddings_model = get_llm_provider().get_embedding_model()

        for row in rows:
            if row.embedding:
                vec = _bytes_to_embed(row.embedding).reshape(1, -1)
            else:
                if hasattr(embeddings_model, "aembed_query"):
                    raw = await embeddings_model.aembed_query(row.question)
                else:
                    raw = embeddings_model.embed_query(row.question)
                vec = np.asarray(raw, dtype=np.float32).reshape(1, -1)
                row.embedding = _embed_to_bytes(vec.reshape(-1))
            vectors.append(vec)
            ids.append(row.id)

        mat = np.vstack(vectors).astype(np.float32)
        _normalize(mat)
        index = faiss.IndexFlatIP(mat.shape[1])
        index.add(mat)
        self._save_index(connection_id, index, ids)
        await session.flush()
        return len(ids)

    @staticmethod
    def format_few_shot(records: list[dict[str, Any]]) -> str:
        if not records:
            return "(none)"
        parts: list[str] = []
        for rec in records:
            q = rec.get("question", "")
            sql = rec.get("sql", "")
            parts.append(f"Q: {q}\nSQL:\n{sql}")
        return "\n\n".join(parts)
