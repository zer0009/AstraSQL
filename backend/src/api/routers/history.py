from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from src.api.deps import DbSession
from src.api.schemas import FeedbackOut, FeedbackRequest, HistoryOut
from src.context import GoldenRecordsStore
from src.storage.models import QueryHistory

router = APIRouter(tags=["history"])

golden_store = GoldenRecordsStore()


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
