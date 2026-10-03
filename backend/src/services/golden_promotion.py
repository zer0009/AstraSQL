"""Promote reviewed Q→SQL pairs into golden records with soft execute gates."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.verified_cache import normalize_question
from src.context.golden_records import GoldenRecordsStore
from src.storage.models import Connection, GoldenRecord

logger = logging.getLogger(__name__)


async def find_duplicate_golden(
    db: AsyncSession,
    connection_id: str,
    question: str,
) -> GoldenRecord | None:
    """Return an existing golden with the same normalized question, if any."""
    norm = normalize_question(question)
    if not norm:
        return None
    result = await db.execute(
        select(GoldenRecord).where(GoldenRecord.connection_id == connection_id)
    )
    for row in result.scalars().all():
        if normalize_question(row.question or "") == norm:
            return row
    return None


async def try_execute_readonly(connection: Connection | None, sql: str) -> bool:
    """Best-effort readonly execute before promoting to golden. False on failure."""
    if connection is None or not sql.strip():
        return False
    try:
        from src.providers.database.registry import provider_from_connection

        provider = provider_from_connection(connection)
        try:
            await provider.execute_readonly(sql, max_rows=1)
            return True
        finally:
            await provider.close()
    except Exception:
        logger.info(
            "Golden promote execute check failed for connection %s",
            getattr(connection, "id", None),
            exc_info=True,
        )
        return False


def _supports_execute_gate(db_type: str) -> bool:
    from src.providers.database.registry import get_provider_class

    try:
        cls = get_provider_class(db_type)
    except ValueError:
        return True
    # Capability methods need no live connection — construct with placeholders.
    probe = cls(host="", port=0, database="", username="", password="")
    return bool(probe.supports_execute_gate())


async def promote_golden(
    db: AsyncSession,
    *,
    connection_id: str,
    question: str,
    sql: str,
    golden_store: GoldenRecordsStore | None = None,
) -> GoldenRecord | None:
    """Promote Q→SQL to golden with empty/dedup/execute gates. None if rejected."""
    store = golden_store or GoldenRecordsStore()
    cleaned = (sql or "").strip()
    if not cleaned:
        logger.info("Skipping golden promote: empty SQL")
        return None

    existing = await find_duplicate_golden(db, connection_id, question)
    if existing is not None:
        # Dedup: keep existing record (optionally refresh SQL if empty — keep minimal).
        return existing

    connection = await db.get(Connection, connection_id)
    # Optional execute check — skip providers that do not support the gate
    # (MySQL/MSSQL stubs). Soft gate: log failure but still promote.
    if connection is not None and _supports_execute_gate(
        getattr(connection, "db_type", "") or ""
    ):
        await try_execute_readonly(connection, cleaned)

    golden = await store.add(
        db,
        connection_id=connection_id,
        question=question,
        sql=cleaned,
    )
    await store.rebuild_index(db, connection_id)
    return golden
