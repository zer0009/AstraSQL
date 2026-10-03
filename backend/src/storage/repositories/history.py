"""QueryHistory persistence helpers."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.state import AgentState
from src.agent.utils import confidence_to_float
from src.storage.models import ChatSession, Connection, QueryHistory


def _ambiguity_json(state: AgentState) -> str | None:
    """Serialize ambiguity diagnostics for QueryHistory."""
    ambiguity = state.get("ambiguity")
    if not isinstance(ambiguity, dict) or not ambiguity:
        return None
    try:
        return json.dumps(ambiguity, default=str)
    except (TypeError, ValueError):
        return None


async def persist_query_history(
    session: AsyncSession,
    connection: Connection,
    state: AgentState,
    session_id: str | None = None,
) -> QueryHistory | None:
    """Persist a QueryHistory row when SQL was produced or clarification asked."""
    sql = (state.get("corrected_sql") or state.get("sql") or "").strip()
    raw_ambiguity = state.get("ambiguity")
    ambiguity: dict = raw_ambiguity if isinstance(raw_ambiguity, dict) else {}
    clarifying = bool(ambiguity.get("should_clarify")) or (
        str(state.get("intent") or "").upper() == "CLARIFICATION_NEEDED"
    )
    # Persist clarify turns (empty SQL) so diagnostics survive; skip empty no-ops.
    if not sql and not clarifying:
        return None

    raw_results = state.get("results")
    results: dict = raw_results if isinstance(raw_results, dict) else {}
    row_count = results.get("row_count")
    follow_ups = state.get("follow_ups") or []
    ambiguity_text = _ambiguity_json(state)

    turn_index: int | None = None
    chat_session: ChatSession | None = None
    if session_id:
        chat_session = await session.get(ChatSession, session_id)
        if chat_session is None:
            raise ValueError(f"Session not found: {session_id}")
        if chat_session.connection_id != connection.id:
            raise ValueError("Session does not belong to this connection")
        count_result = await session.execute(
            select(func.count())
            .select_from(QueryHistory)
            .where(QueryHistory.session_id == session_id)
        )
        turn_index = int(count_result.scalar_one() or 0)

    record = QueryHistory(
        connection_id=connection.id,
        session_id=session_id,
        turn_index=turn_index,
        question=state.get("question") or "",
        sql=sql or "",
        result_row_count=int(row_count) if row_count is not None else None,
        confidence=confidence_to_float(state.get("confidence")),
        trust_level=(str(state.get("trust_level") or "").strip().lower() or None),
        explanation=state.get("answer"),
        follow_ups=json.dumps(follow_ups) if follow_ups else None,
        ambiguity_json=ambiguity_text,
    )
    session.add(record)

    if chat_session is not None:
        chat_session.updated_at = datetime.utcnow()
        if not chat_session.title:
            question = (state.get("question") or "").strip()
            if question:
                chat_session.title = question[:60]

    try:
        await session.commit()
        await session.refresh(record)
    except Exception:
        await session.rollback()
        raise
    return record
