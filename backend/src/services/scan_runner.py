"""Background schema scan runner."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from src.context.auto_enricher import SchemaAutoEnricher
from src.context.retriever import scan_connection_schema
from src.context.schema_linker import SchemaLinker
from src.providers.database.registry import provider_from_connection
from src.services.scan_jobs import ScanJob, ScanStatus, update_job
from src.storage.database import async_session_factory
from src.storage.models import Connection, SchemaCache

logger = logging.getLogger(__name__)


async def run_scan_job(job: ScanJob) -> None:
    """Execute schema scan in its own DB session (safe after HTTP request returns)."""
    update_job(
        job,
        status=ScanStatus.RUNNING,
        phase="listing",
        message="Listing tables…",
    )

    provider = None
    try:
        async with async_session_factory() as session:
            connection = await session.get(Connection, job.connection_id)
            if connection is None:
                update_job(
                    job,
                    status=ScanStatus.FAILED,
                    phase="done",
                    message="Connection not found",
                    error="Connection not found",
                    finished_at=datetime.now(timezone.utc),
                )
                return

            provider = provider_from_connection(connection)

            def on_progress(
                *,
                phase: str,
                message: str,
                current_table: Optional[str] = None,
                tables_total: Optional[int] = None,
                tables_done: Optional[int] = None,
                table_just_done: Optional[str] = None,
            ) -> None:
                kwargs: dict = {
                    "phase": phase,
                    "message": message,
                    "current_table": current_table,
                }
                if tables_total is not None:
                    kwargs["tables_total"] = tables_total
                if tables_done is not None:
                    kwargs["tables_done"] = tables_done
                if table_just_done:
                    cached = list(job.tables_cached)
                    cached.append(table_just_done)
                    kwargs["tables_cached"] = cached
                update_job(job, **kwargs)

            caches = await scan_connection_schema(
                session,
                connection,
                provider,
                progress=on_progress,
            )
            await session.commit()

            # Re-load after commit so ORM attrs are available (expire_on_commit).
            result = await session.execute(
                select(SchemaCache).where(
                    SchemaCache.connection_id == connection.id
                )
            )
            caches = list(result.scalars().all())
            table_count = len(caches)

            # Auto-enrich descriptions (one LLM call per table), then rebuild FAISS.
            update_job(
                job,
                phase="enriching",
                message="Enriching table descriptions…",
                current_table=None,
                tables_done=0,
                tables_total=table_count,
            )
            enriched = 0
            enrich_note = ""
            try:
                enriched = await SchemaAutoEnricher().enrich_connection(
                    session,
                    connection.id,
                    caches,
                    progress=on_progress,
                )
                # Enrichments are committed per-table inside SchemaAutoEnricher.
                if enriched > 0:
                    update_job(
                        job,
                        phase="indexing",
                        message="Rebuilding search index with descriptions…",
                        current_table=None,
                    )
                    await SchemaLinker().build_table_index(
                        session, connection.id
                    )
                enrich_note = (
                    f", {enriched} enriched" if enriched > 0 else ""
                )
            except Exception:
                # Enrichment is best-effort — scan itself already succeeded.
                logger.exception(
                    "Auto-enrich failed for connection %s (scan still kept)",
                    job.connection_id,
                )
                await session.rollback()
                enrich_note = " (description enrichment skipped)"

            update_job(
                job,
                status=ScanStatus.COMPLETED,
                phase="done",
                message=f"Scan complete — {table_count} tables cached{enrich_note}",
                tables_done=table_count,
                tables_total=max(job.tables_total, table_count),
                current_table=None,
                last_scanned_at=connection.last_scanned_at,
                finished_at=datetime.now(timezone.utc),
            )
    except Exception as exc:
        logger.exception("Schema scan failed for connection %s", job.connection_id)
        update_job(
            job,
            status=ScanStatus.FAILED,
            phase="done",
            message="Schema scan failed",
            error=str(exc),
            finished_at=datetime.now(timezone.utc),
        )
    finally:
        if provider is not None:
            try:
                await provider.close()
            except Exception:
                pass
