"""In-process cache of formatted enriched schema text per connection."""

from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}
_TTL_SECONDS = 300.0


def get_cached_schema_text(connection_id: str, version: str) -> str | None:
    """Return cached schema text when version matches and not expired."""
    with _LOCK:
        entry = _CACHE.get(connection_id)
        if not entry:
            return None
        if entry.get("version") != version:
            return None
        if time.monotonic() - float(entry.get("ts") or 0) > _TTL_SECONDS:
            _CACHE.pop(connection_id, None)
            return None
        text = entry.get("text")
        return str(text) if text else None


def set_cached_schema_text(connection_id: str, version: str, text: str) -> None:
    with _LOCK:
        _CACHE[connection_id] = {
            "version": version,
            "text": text,
            "ts": time.monotonic(),
        }


def invalidate_schema_text(connection_id: str | None = None) -> None:
    """Drop cached schema for one connection, or all when ``connection_id`` is None."""
    with _LOCK:
        if connection_id is None:
            _CACHE.clear()
        else:
            _CACHE.pop(connection_id, None)


def schema_version_token(
    *,
    table_count: int,
    last_scanned_at: Any = None,
    enrichment_count: int = 0,
    sample_rows: int = 2,
) -> str:
    """Cheap version string invalidated by scan / enrichment / sample-row setting."""
    scanned = ""
    if last_scanned_at is not None:
        scanned = getattr(last_scanned_at, "isoformat", lambda: str(last_scanned_at))()
    return f"{table_count}:{scanned}:{enrichment_count}:{sample_rows}"
