from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select

from src.api.deps import DbSession
from src.api.schemas import FeedbackOut, FeedbackRequest, HistoryOut, HistoryStatsOut
from src.context import GoldenRecordsStore
from src.storage.models import QueryHistory

router = APIRouter(tags=["history"])

golden_store = GoldenRecordsStore()

# Matches frontend confidenceLevel / confidence_to_float mapping.
_HIGH = 0.85
_MEDIUM = 0.4


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

    if body.rating == 1:
        golden = await golden_store.add(
            db,
            connection_id=row.connection_id,
            question=row.question,
            sql=row.sql,
        )
        await golden_store.rebuild_index(db, row.connection_id)
        golden_record_id = golden.id
    elif body.rating == -1 and body.corrected_sql:
        corrected = body.corrected_sql.strip()
        if corrected:
            golden = await golden_store.add(
                db,
                connection_id=row.connection_id,
                question=row.question,
                sql=corrected,
            )
            await golden_store.rebuild_index(db, row.connection_id)
            golden_record_id = golden.id

    await db.flush()
    return FeedbackOut(
        id=row.id,
        user_rating=row.user_rating,
        golden_record_id=golden_record_id,
    )
