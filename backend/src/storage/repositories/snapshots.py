"""RunSnapshot persistence for resumable clarifications."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.state import AgentState
from src.storage.models import RunSnapshot


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return None


async def persist_run_snapshot(
    session: AsyncSession,
    *,
    connection_id: str,
    state: AgentState,
    session_id: str | None = None,
    history_id: str | None = None,
) -> RunSnapshot | None:
    """Persist enough state to resume generate with a chosen reading."""
    question = str(state.get("question") or "").strip()
    if not question or not connection_id:
        return None
    context = state.get("context") if isinstance(state.get("context"), dict) else None
    ambiguity = state.get("ambiguity") if isinstance(state.get("ambiguity"), dict) else {}
    alternatives = (
        ambiguity.get("alternatives")
        or state.get("clarification_options")
        or state.get("follow_ups")
        or []
    )
    run_id = str(state.get("run_id") or "").strip() or None
    row = RunSnapshot(
        id=run_id,
        connection_id=connection_id,
        session_id=session_id,
        history_id=history_id,
        question=question,
        context_json=_json_or_none(context),
        assumption=str(state.get("assumption") or "") or None,
        alternatives_json=_json_or_none(list(alternatives) if alternatives else []),
        ambiguity_json=_json_or_none(ambiguity or None),
        sql=(state.get("corrected_sql") or state.get("sql") or None),
        context_version=str((context or {}).get("schema_version") or "") or None,
    )
    session.add(row)
    try:
        await session.commit()
        await session.refresh(row)
    except Exception:
        await session.rollback()
        raise
    return row


async def load_run_snapshot(
    session: AsyncSession, run_id: str
) -> RunSnapshot | None:
    if not run_id:
        return None
    return await session.get(RunSnapshot, run_id)


def snapshot_to_state(row: RunSnapshot) -> dict[str, Any]:
    """Rebuild agent state fields from a stored snapshot."""
    context: dict[str, Any] = {}
    if row.context_json:
        try:
            parsed = json.loads(row.context_json)
            if isinstance(parsed, dict):
                context = parsed
        except (json.JSONDecodeError, TypeError):
            context = {}
    alternatives: list[str] = []
    if row.alternatives_json:
        try:
            raw = json.loads(row.alternatives_json)
            if isinstance(raw, list):
                alternatives = [str(x) for x in raw if str(x).strip()]
        except (json.JSONDecodeError, TypeError):
            alternatives = []
    ambiguity: dict[str, Any] = {}
    if row.ambiguity_json:
        try:
            parsed = json.loads(row.ambiguity_json)
            if isinstance(parsed, dict):
                ambiguity = parsed
        except (json.JSONDecodeError, TypeError):
            ambiguity = {}
    return {
        "connection_id": row.connection_id,
        "question": row.question,
        "context": context,
        "assumption": row.assumption,
        "clarification_options": alternatives,
        "follow_ups": alternatives,
        "ambiguity": {
            **ambiguity,
            "should_clarify": False,
            "alternatives": alternatives,
        },
        "sql": row.sql or "",
        "corrected_sql": row.sql or "",
        "run_id": row.id,
        "allow_clarify": False,
        "retries": 0,
        "steps": [],
        "error": None,
    }
