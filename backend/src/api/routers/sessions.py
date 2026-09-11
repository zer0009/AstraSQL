from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.api.deps import DbSession
from src.api.schemas import (
    SessionCreate,
    SessionDetailOut,
    SessionOut,
    SessionRename,
)
from src.storage.models import ChatSession, Connection, QueryHistory

router = APIRouter(tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(body: SessionCreate, db: DbSession) -> ChatSession:
    conn = await db.get(Connection, body.connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    title = (body.title or "").strip() or None
    if title and len(title) > 255:
        title = title[:255]

    session = ChatSession(connection_id=body.connection_id, title=title)
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    db: DbSession,
    connection_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ChatSession]:
    stmt = select(ChatSession).order_by(ChatSession.updated_at.desc())
    if connection_id is not None:
        stmt = stmt.where(ChatSession.connection_id == connection_id)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{session_id}", response_model=SessionDetailOut)
async def get_session(session_id: str, db: DbSession) -> SessionDetailOut:
    stmt = (
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.queries))
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    queries = sorted(
        session.queries,
        key=lambda q: (
            q.turn_index if q.turn_index is not None else 10**9,
            q.created_at,
        ),
    )
    return SessionDetailOut(
        id=session.id,
        connection_id=session.connection_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        queries=queries,
    )


@router.patch("/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: str, body: SessionRename, db: DbSession
) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title must not be empty")
    session.title = title[:255]
    session.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(session)
    return session


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, db: DbSession) -> None:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Explicitly detach history rows (ON DELETE SET NULL also covers this).
    result = await db.execute(
        select(QueryHistory).where(QueryHistory.session_id == session_id)
    )
    for row in result.scalars().all():
        row.session_id = None
        row.turn_index = None

    await db.delete(session)
    await db.flush()
