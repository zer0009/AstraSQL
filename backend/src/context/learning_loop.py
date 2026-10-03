"""Governed per-connection learning loop.

Mutates a semantic-layer dict in place (caller persists ``semantic_layer_json``).
No global hardcoding — all memory is scoped to the connection's layer.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_MAX_REVIEWED = 200
_MAX_REPAIR = 100
_MAX_CONVENTIONS = 100


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_lists(layer: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(layer.get("reviewed_queries"), list):
        layer["reviewed_queries"] = []
    if not isinstance(layer.get("repair_memory"), list):
        layer["repair_memory"] = []
    if not isinstance(layer.get("learned_conventions"), list):
        layer["learned_conventions"] = []
    return layer


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_]+", (text or "").lower()) if len(t) > 1}


def record_reviewed_query(
    semantic_layer_dict: dict[str, Any],
    question: str,
    sql: str,
) -> dict[str, Any]:
    """Append a thumbs-up / verified Q→SQL pair into the layer."""
    layer = _ensure_lists(semantic_layer_dict)
    q = (question or "").strip()
    s = (sql or "").strip()
    if not q or not s:
        return layer

    entry = {"question": q, "sql": s, "recorded_at": _utcnow_iso()}
    # Dedup by normalized question — keep latest SQL.
    norm = re.sub(r"\s+", " ", q.lower())
    existing = layer["reviewed_queries"]
    layer["reviewed_queries"] = [
        e
        for e in existing
        if re.sub(r"\s+", " ", str(e.get("question") or "").lower()) != norm
    ]
    layer["reviewed_queries"].append(entry)
    layer["reviewed_queries"] = layer["reviewed_queries"][-_MAX_REVIEWED:]
    return layer


def record_repair_memory(
    semantic_layer_dict: dict[str, Any],
    *,
    error_pattern: str,
    fix_hint: str,
    sql_before: str,
    sql_after: str,
) -> dict[str, Any]:
    """Append a repair memory entry (wrong → corrected SQL + hint)."""
    layer = _ensure_lists(semantic_layer_dict)
    before = (sql_before or "").strip()
    after = (sql_after or "").strip()
    if not after:
        return layer

    entry = {
        "error_pattern": (error_pattern or "").strip(),
        "fix_hint": (fix_hint or "").strip(),
        "sql_before": before,
        "sql_after": after,
        "recorded_at": _utcnow_iso(),
    }
    layer["repair_memory"].append(entry)
    layer["repair_memory"] = layer["repair_memory"][-_MAX_REPAIR:]
    return layer


def record_learned_convention(
    semantic_layer_dict: dict[str, Any],
    convention: str,
) -> dict[str, Any]:
    """Append a free-text business convention learned from feedback."""
    layer = _ensure_lists(semantic_layer_dict)
    text = (convention or "").strip()
    if not text:
        return layer
    norms = {str(c).strip().lower() for c in layer["learned_conventions"]}
    if text.lower() not in norms:
        layer["learned_conventions"].append(text)
        layer["learned_conventions"] = layer["learned_conventions"][-_MAX_CONVENTIONS:]
    return layer


def retrieve_repair_hints(
    semantic_layer_dict: dict[str, Any],
    question: str,
    sql: str,
    *,
    top_k: int = 3,
) -> list[str]:
    """Return top-k fix hints by token overlap with question + SQL."""
    layer = semantic_layer_dict if isinstance(semantic_layer_dict, dict) else {}
    memory = layer.get("repair_memory") or []
    if not isinstance(memory, list) or not memory:
        return []

    query_tokens = _tokenize(question) | _tokenize(sql)
    if not query_tokens:
        return []

    scored: list[tuple[float, str]] = []
    for entry in memory:
        if not isinstance(entry, dict):
            continue
        hint = str(entry.get("fix_hint") or "").strip()
        blob_tokens = (
            _tokenize(str(entry.get("error_pattern") or ""))
            | _tokenize(str(entry.get("sql_before") or ""))
            | _tokenize(str(entry.get("sql_after") or ""))
            | _tokenize(hint)
        )
        if not blob_tokens:
            continue
        overlap = len(query_tokens & blob_tokens)
        if overlap <= 0:
            continue
        score = overlap / max(len(query_tokens), 1)
        text = hint or str(entry.get("error_pattern") or "").strip()
        if not text and entry.get("sql_after"):
            text = f"Prefer SQL like: {str(entry['sql_after'])[:200]}"
        if text:
            scored.append((score, text))

    scored.sort(key=lambda x: (-x[0], x[1]))
    # Dedup hints preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for _score, text in scored:
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= top_k:
            break
    return out


async def verify_repair_against_evidence(db_provider: Any, sql: str) -> bool:
    """Execute SQL readonly; True if it succeeds (evidence gate)."""
    cleaned = (sql or "").strip()
    if not cleaned or db_provider is None:
        return False
    try:
        await db_provider.execute_readonly(cleaned, max_rows=1)
        return True
    except Exception:
        logger.debug("verify_repair_against_evidence failed", exc_info=True)
        return False
