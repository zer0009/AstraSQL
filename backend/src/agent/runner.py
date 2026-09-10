from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.graph import build_graph, get_graph
from src.agent.state import AgentState
from src.agent.utils import confidence_to_float
from src.providers.database.registry import provider_from_connection
from src.storage.models import Connection, QueryHistory


def _initial_state(connection: Connection, question: str) -> AgentState:
    return {
        "connection_id": connection.id,
        "question": question,
        "retries": 0,
        "steps": [],
        "retry_context": "",
        "error": None,
    }


def _run_config(
    session: AsyncSession,
    connection: Connection,
    db_provider: Any,
) -> dict[str, Any]:
    return {
        "configurable": {
            "session": session,
            "connection": connection,
            "db_provider": db_provider,
        }
    }


def _sse_safe(value: Any) -> Any:
    """Make values JSON-serializable for SSE payloads."""
    try:
        json.dumps(value, default=str)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


def _compact_state(state: AgentState) -> dict[str, Any]:
    """SSE-safe state without huge context blobs (enriched schema, etc.)."""
    results = state.get("results") or {}
    # Cap rows for SSE — full rows already executed server-side for history
    rows = results.get("rows") if isinstance(results, dict) else None
    if isinstance(rows, list) and len(rows) > 100:
        results = {
            **results,
            "rows": rows[:100],
            "row_count": results.get("row_count", len(rows)),
            "truncated": True,
        }
    return {
        "connection_id": state.get("connection_id"),
        "question": state.get("question"),
        "intent": state.get("intent"),
        "sql": state.get("sql"),
        "corrected_sql": state.get("corrected_sql"),
        "results": results,
        "retries": state.get("retries"),
        "error": state.get("error"),
        "confidence": state.get("confidence"),
        "answer": state.get("answer"),
        "key_finding": state.get("key_finding"),
        "assumption": state.get("assumption"),
        "follow_ups": state.get("follow_ups") or [],
        # Steps stream via "step" events — omit from done to keep SSE JSON small
    }


def _compact_update(update: dict[str, Any]) -> dict[str, Any]:
    """Drop non-UI fields from per-node stream updates."""
    skip = {"context", "retry_context", "intent_reason"}
    return {k: v for k, v in update.items() if k not in skip and k != "steps"}


async def _persist_history(
    session: AsyncSession,
    connection: Connection,
    state: AgentState,
) -> Optional[QueryHistory]:
    """Persist a QueryHistory row when SQL was produced."""
    sql = (state.get("corrected_sql") or state.get("sql") or "").strip()
    if not sql:
        return None

    results = state.get("results") or {}
    row_count = results.get("row_count")
    follow_ups = state.get("follow_ups") or []
    record = QueryHistory(
        connection_id=connection.id,
        question=state.get("question") or "",
        sql=sql,
        result_row_count=int(row_count) if row_count is not None else None,
        confidence=confidence_to_float(state.get("confidence")),
        explanation=state.get("answer"),
        follow_ups=json.dumps(follow_ups) if follow_ups else None,
    )
    session.add(record)
    try:
        await session.commit()
        await session.refresh(record)
    except Exception:
        await session.rollback()
        raise
    return record


async def run_query(
    session: AsyncSession,
    connection: Connection,
    question: str,
) -> AgentState:
    """Run the full agent graph and persist QueryHistory on completion."""
    provider = provider_from_connection(connection)
    try:
        graph = get_graph()
        initial = _initial_state(connection, question)
        result = await graph.ainvoke(
            initial,
            config=_run_config(session, connection, provider),
        )
        await _persist_history(session, connection, result)
        return result
    finally:
        await provider.close()


async def stream_query(
    session: AsyncSession,
    connection: Connection,
    question: str,
) -> AsyncIterator[dict[str, Any]]:
    """Stream SSE-friendly events for each graph node / agent step."""
    provider = provider_from_connection(connection)
    final_state: AgentState = dict(_initial_state(connection, question))
    try:
        graph = get_graph()
        config = _run_config(session, connection, provider)
        yield {
            "event": "start",
            "connection_id": connection.id,
            "question": question,
        }

        async for chunk in graph.astream(
            final_state,
            config=config,
            stream_mode="updates",
        ):
            if not isinstance(chunk, dict):
                continue
            for node_name, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                prev_step_len = len(final_state.get("steps") or [])
                final_state.update(update)
                yield {
                    "event": "node",
                    "node": node_name,
                    "data": _sse_safe(_compact_update(update)),
                }
                steps = update.get("steps") or []
                for step in steps[prev_step_len:]:
                    yield {
                        "event": "step",
                        "node": node_name,
                        "step": _sse_safe(step),
                    }

        history = await _persist_history(session, connection, final_state)
        done_payload = _compact_state(final_state)
        done_payload["history_id"] = history.id if history else None
        yield {
            "event": "done",
            "data": _sse_safe(done_payload),
        }
        # Compact result for UI — no bulky steps array
        yield {
            "event": "result",
            "data": _sse_safe(
                {
                    "answer": done_payload.get("answer"),
                    "key_finding": done_payload.get("key_finding"),
                    "sql": done_payload.get("corrected_sql")
                    or done_payload.get("sql"),
                    "results": done_payload.get("results"),
                    "confidence": done_payload.get("confidence"),
                    "follow_ups": done_payload.get("follow_ups"),
                    "history_id": done_payload.get("history_id"),
                    "error": done_payload.get("error"),
                }
            ),
        }
    except Exception as exc:
        yield {
            "event": "error",
            "error": str(exc),
            "data": _sse_safe(dict(final_state)),
        }
        raise
    finally:
        await provider.close()


# Re-export build_graph for callers that want a fresh compile.
__all__ = [
    "run_query",
    "stream_query",
    "build_graph",
    "get_graph",
]
