"""Seed Spider train questions as golden NL→SQL records.

Does **not** download train.json. If the file is missing under
``eval/benchmarks/data/spider``, helpers return empty / skip gracefully.

CLI / script usage::

    # From the backend/ directory, with PYTHONPATH=.
    python -c "
    import asyncio
    from src.eval.spider_fewshot import load_spider_train, seed_goldens_for_db
    from src.storage.database import async_session_factory

    async def main():
        items = load_spider_train()
        if not items:
            print('train.json not found; skip')
            return
        async with async_session_factory() as session:
            n = await seed_goldens_for_db(
                session,
                connection_id='YOUR_CONNECTION_ID',
                db_id='concert_singer',
                items=items,
                limit=20,
            )
            await session.commit()
            print(f'seeded {n} goldens')

    asyncio.run(main())
    "
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.context.golden_records import GoldenRecordsStore
from src.eval.spider_data import DATA_DIR

logger = logging.getLogger(__name__)

_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_WS_RE = re.compile(r"\s+")


def question_skeleton(question: str) -> str:
    """Mask quoted strings and numbers for embedding / similarity matching."""
    text = question or ""
    text = _QUOTED_RE.sub("<STR>", text)
    text = _NUMBER_RE.sub("<NUM>", text)
    text = _WS_RE.sub(" ", text).strip()
    # Lowercase prose but keep placeholder tokens uppercase.
    parts = re.split(r"(<STR>|<NUM>)", text)
    return "".join(
        p if p in ("<STR>", "<NUM>") else p.lower() for p in parts
    )


def find_spider_train_path() -> Optional[Path]:
    """Locate train.json under the Spider data tree without downloading."""
    candidates = [
        DATA_DIR / "spider_data" / "train.json",
        DATA_DIR / "train.json",
        DATA_DIR / "spider_data" / "train_spider.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    # Shallow search (avoid walking huge trees if present).
    if DATA_DIR.is_dir():
        for path in DATA_DIR.glob("**/train.json"):
            if path.is_file():
                return path
        for path in DATA_DIR.glob("**/train_spider.json"):
            if path.is_file():
                return path
    return None


def ensure_spider_train() -> Optional[Path]:
    """Return path to train.json if present; never download. None if missing."""
    return find_spider_train_path()


def load_spider_train() -> list[dict[str, Any]]:
    """Load Spider train.json when present; otherwise return []."""
    path = ensure_spider_train()
    if path is None:
        logger.info(
            "Spider train.json not found under %s — skipping few-shot seed",
            DATA_DIR,
        )
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to read Spider train from %s", path)
        return []
    if not isinstance(data, list):
        logger.warning("Unexpected Spider train format at %s", path)
        return []
    return data


async def seed_goldens_for_db(
    session: AsyncSession,
    connection_id: str,
    db_id: str,
    items: list[dict[str, Any]],
    limit: int = 20,
) -> int:
    """Insert GoldenRecord rows for one Spider db's train questions.

    Uses ``question`` + ``query`` (gold SQL). Skips questions already present
    for this connection. Returns the number of newly inserted records.
    """
    if limit <= 0 or not items:
        return 0

    scoped = [
        item
        for item in items
        if str(item.get("db_id") or "") == db_id
        and str(item.get("question") or "").strip()
        and str(item.get("query") or item.get("sql") or "").strip()
    ]
    if not scoped:
        return 0

    store = GoldenRecordsStore()
    existing = await store.list(session, connection_id)
    known = {str(row.question).strip() for row in existing}

    inserted = 0
    for item in scoped:
        if inserted >= limit:
            break
        question = str(item.get("question") or "").strip()
        sql = str(item.get("query") or item.get("sql") or "").strip()
        if not question or not sql:
            continue
        if question in known:
            continue
        await store.add(session, connection_id, question, sql)
        known.add(question)
        inserted += 1

    return inserted
