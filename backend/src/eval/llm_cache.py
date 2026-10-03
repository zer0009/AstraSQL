"""Filesystem record/replay cache for LLM chat calls (paid evals).

Enabled when env ``ASTRASQL_LLM_CACHE=1``. Keyed by SHA-256 of
``(model, messages)``. Safe no-op when disabled.

Usage::

    from src.eval.llm_cache import cached_chat, llm_cache_enabled

    if llm_cache_enabled():
        text = await cached_chat(model, messages, invoke_fn=my_ainvoke)
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = _BACKEND / "eval" / "results" / "llm_cache"


def llm_cache_enabled() -> bool:
    return (os.environ.get("ASTRASQL_LLM_CACHE") or "").strip() in {"1", "true", "True", "yes"}


def cache_dir() -> Path:
    raw = (os.environ.get("ASTRASQL_LLM_CACHE_DIR") or "").strip()
    path = Path(raw) if raw else DEFAULT_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_messages(messages: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages or []:
        if isinstance(m, dict):
            role = str(m.get("role") or m.get("type") or "")
            content = m.get("content")
            if content is None and "text" in m:
                content = m.get("text")
            out.append({"role": role, "content": str(content or "")})
            continue
        role = str(getattr(m, "type", None) or getattr(m, "role", "") or "")
        content = getattr(m, "content", None)
        if isinstance(content, list):
            # LangChain multimodal-ish content blocks
            parts = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    parts.append(str(block["text"]))
                else:
                    parts.append(str(block))
            content = "\n".join(parts)
        out.append({"role": role, "content": str(content or "")})
    return out


def make_cache_key(model: str, messages: Any) -> str:
    payload = {
        "model": (model or "").strip(),
        "messages": _normalize_messages(messages),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _path_for(key: str) -> Path:
    return cache_dir() / f"{key}.json"


def read_cache(model: str, messages: Any) -> str | None:
    if not llm_cache_enabled():
        return None
    key = make_cache_key(model, messages)
    path = _path_for(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    text = data.get("response")
    return str(text) if text is not None else None


def write_cache(model: str, messages: Any, response: str) -> None:
    if not llm_cache_enabled():
        return
    key = make_cache_key(model, messages)
    path = _path_for(key)
    payload = {
        "key": key,
        "model": (model or "").strip(),
        "messages": _normalize_messages(messages),
        "response": response,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def cached_chat(
    model: str,
    messages: Any,
    *,
    invoke_fn: Callable[[Any], Awaitable[Any]],
    extract_text: Callable[[Any], str] | None = None,
) -> str:
    """Replay from disk when present; otherwise call ``invoke_fn`` and record.

    ``invoke_fn`` receives ``messages`` and should return a LangChain-like
    message or a string. When cache is disabled, always calls ``invoke_fn``.
    """
    hit = read_cache(model, messages)
    if hit is not None:
        return hit

    result = await invoke_fn(messages)

    def _default_extract(res: Any) -> str:
        if isinstance(res, str):
            return res
        content = getattr(res, "content", None)
        if content is not None:
            return str(content)
        return str(res)

    text = (extract_text or _default_extract)(result)
    write_cache(model, messages, text)
    return text
