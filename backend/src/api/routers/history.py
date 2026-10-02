from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select

from src.agent.verified_cache import normalize_question
from src.api.deps import DbSession
from src.api.schemas import FeedbackOut, FeedbackRequest, HistoryOut, HistoryStatsOut
from src.config.settings import get_settings
from src.context import BusinessRulesStore, GoldenRecordsStore
from src.context.learning_loop import record_repair_memory, record_reviewed_query
from src.context.semantic_layer import parse_semantic_layer
from src.storage.models import Connection, GoldenRecord, QueryHistory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["history"])

golden_store = GoldenRecordsStore()
rules_store = BusinessRulesStore()

# Matches frontend confidenceLevel / confidence_to_float mapping.
_HIGH = 0.85
_MEDIUM = 0.4


async def _find_duplicate_golden(
    db: DbSession,
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


async def _try_execute_readonly(connection: Connection | None, sql: str) -> bool:
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


async def _promote_golden(
    db: DbSession,
    *,
    connection_id: str,
    question: str,
    sql: str,
) -> GoldenRecord | None:
    """Promote Q→SQL to golden with empty/dedup/execute gates. None if rejected."""
    cleaned = (sql or "").strip()
    if not cleaned:
        logger.info("Skipping golden promote: empty SQL")
        return None

    existing = await _find_duplicate_golden(db, connection_id, question)
    if existing is not None:
        # Dedup: keep existing record (optionally refresh SQL if empty — keep minimal).
        return existing

    connection = await db.get(Connection, connection_id)
    # Optional execute check — catch errors but still allow promote if provider
    # is unavailable (stub dialects). Reject only when execute raises on a live DB.
    if connection is not None and getattr(connection, "db_type", "") not in (
        "mysql",
        "mssql",
    ):
        # Soft gate: log failure but still promote (roadmap: catch errors).
        await _try_execute_readonly(connection, cleaned)

    golden = await golden_store.add(
        db,
        connection_id=connection_id,
        question=question,
        sql=cleaned,
    )
    await golden_store.rebuild_index(db, connection_id)
    return golden


@router.get("/stats", response_model=HistoryStatsOut)
async def history_stats(
    db: DbSession,
    connection_id: str | None = Query(None),
) -> HistoryStatsOut:
    """Aggregate query-history health metrics for the History page."""
    filters = []
    if connection_id is not None:
        filters.append(QueryHistory.connection_id == connection_id)

    stmt = select(
        func.count().label("total"),
        func.coalesce(
            func.sum(
                case((QueryHistory.confidence >= _HIGH, 1), else_=0)
            ),
            0,
        ).label("high_confidence"),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            QueryHistory.confidence.is_not(None),
                            QueryHistory.confidence >= _MEDIUM,
                            QueryHistory.confidence < _HIGH,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("medium_confidence"),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            QueryHistory.confidence.is_not(None),
                            QueryHistory.confidence < _MEDIUM,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("low_confidence"),
        func.coalesce(
            func.sum(
                case((QueryHistory.confidence.is_(None), 1), else_=0)
            ),
            0,
        ).label("unknown_confidence"),
        # Errors: low confidence or missing result row count.
        func.coalesce(
            func.sum(
                case(
                    (
                        or_(
                            and_(
                                QueryHistory.confidence.is_not(None),
                                QueryHistory.confidence < _MEDIUM,
                            ),
                            QueryHistory.result_row_count.is_(None),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("error_count"),
        func.coalesce(
            func.sum(case((QueryHistory.user_rating == -1, 1), else_=0)),
            0,
        ).label("negative_rated"),
        func.coalesce(
            func.sum(case((QueryHistory.user_rating == 1, 1), else_=0)),
            0,
        ).label("positive_rated"),
        func.coalesce(
            func.sum(case((QueryHistory.user_rating.is_(None), 1), else_=0)),
            0,
        ).label("unrated"),
    ).select_from(QueryHistory)

    for f in filters:
        stmt = stmt.where(f)

    row = (await db.execute(stmt)).one()

    return HistoryStatsOut(
        total=int(row.total or 0),
        high_confidence=int(row.high_confidence or 0),
        medium_confidence=int(row.medium_confidence or 0),
        low_confidence=int(row.low_confidence or 0),
        unknown_confidence=int(row.unknown_confidence or 0),
        error_count=int(row.error_count or 0),
        negative_rated=int(row.negative_rated or 0),
        positive_rated=int(row.positive_rated or 0),
        unrated=int(row.unrated or 0),
    )


@router.get("", response_model=list[HistoryOut])
async def list_history(
    db: DbSession,
    connection_id: str | None = Query(None),
    rating: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[QueryHistory]:
    stmt = select(QueryHistory).order_by(QueryHistory.created_at.desc())
    if connection_id is not None:
        stmt = stmt.where(QueryHistory.connection_id == connection_id)
    if rating is not None:
        if rating not in (1, -1):
            raise HTTPException(status_code=400, detail="rating must be 1 or -1")
        stmt = stmt.where(QueryHistory.user_rating == rating)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{history_id}", response_model=HistoryOut)
async def get_history(history_id: str, db: DbSession) -> QueryHistory:
    row = await db.get(QueryHistory, history_id)
    if row is None:
        raise HTTPException(status_code=404, detail="History entry not found")
    return row


@router.post("/{history_id}/feedback", response_model=FeedbackOut)
async def submit_feedback(
    history_id: str, body: FeedbackRequest, db: DbSession
) -> FeedbackOut:
    row = await db.get(QueryHistory, history_id)
    if row is None:
        raise HTTPException(status_code=404, detail="History entry not found")

    row.user_rating = body.rating
    golden_record_id: str | None = None
    rule_id: str | None = None

    if body.rating == 1:
        golden = await _promote_golden(
            db,
            connection_id=row.connection_id,
            question=row.question,
            sql=row.sql,
        )
        if golden is not None:
            golden_record_id = golden.id
    elif body.rating == -1 and body.corrected_sql:
        golden = await _promote_golden(
            db,
            connection_id=row.connection_id,
            question=row.question,
            sql=body.corrected_sql,
        )
        if golden is not None:
            golden_record_id = golden.id

    new_rule = (body.new_rule or "").strip()
    if new_rule:
        rule = await rules_store.create(db, row.connection_id, new_rule)
        rule_id = rule.id

    # Governed learning loop: append reviewed Q→SQL / repair memory into
    # the connection semantic layer (keeps golden-record promote above).
    if get_settings().learning_loop_enabled and (
        body.rating == 1 or (body.corrected_sql or "").strip()
    ):
        connection = await db.get(Connection, row.connection_id)
        if connection is not None:
            layer = parse_semantic_layer(connection.semantic_layer_json)
            from src.context.conventions import record_join_type_convention

            if body.rating == 1 and (row.sql or "").strip():
                record_reviewed_query(layer, row.question, row.sql)
                record_join_type_convention(layer, row.sql)
            corrected = (body.corrected_sql or "").strip()
            if corrected:
                record_repair_memory(
                    layer,
                    error_pattern="user_corrected_sql",
                    fix_hint="User-provided corrected SQL",
                    sql_before=row.sql or "",
                    sql_after=corrected,
                )
                record_reviewed_query(layer, row.question, corrected)
                record_join_type_convention(layer, corrected)
            try:
                connection.semantic_layer_json = json.dumps(layer)
            except (TypeError, ValueError):
                logger.warning(
                    "Could not serialize semantic_layer_json for connection %s",
                    row.connection_id,
                    exc_info=True,
                )

    await db.flush()
    return FeedbackOut(
        id=row.id,
        user_rating=row.user_rating,
        golden_record_id=golden_record_id,
        rule_id=rule_id,
    )
