from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.agent.nodes.query_validator import validate_syntax
from src.agent.runner import run_query, stream_query
from src.api.deps import DbSession
from src.api.schemas import (
    AgentStateOut,
    ExecuteSqlOut,
    ExecuteSqlRequest,
    QueryRequest,
)
from src.config.settings import get_settings
from src.providers.database.registry import provider_from_connection
from src.storage.models import ChatSession, Connection

router = APIRouter(tags=["query"])


async def _ensure_connection(db: DbSession, connection_id: str) -> Connection:
    conn = await db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


async def _ensure_session(
    db: DbSession, session_id: str | None, connection_id: str
) -> str | None:
    if not session_id:
        return None
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.connection_id != connection_id:
        raise HTTPException(
            status_code=400, detail="Session does not belong to this connection"
        )
    return session_id


def _normalize_sse_item(item: dict[str, Any]) -> dict[str, str]:
    """Map stream_query yields to sse-starlette event payloads."""
    event = item.get("event") or item.get("type") or "message"
    if "data" in item:
        data = item["data"]
    else:
        data = {k: v for k, v in item.items() if k not in ("event", "type")}
    if not isinstance(data, str):
        data = json.dumps(data, default=str)
    return {"event": str(event), "data": data}


@router.post("/execute", response_model=ExecuteSqlOut)
async def execute_sql(body: ExecuteSqlRequest, db: DbSession) -> ExecuteSqlOut:
    """Execute saved SQL directly — no LLM. Used by chat Re-run."""
    connection = await _ensure_connection(db, body.connection_id)
    sql = body.sql.strip().rstrip(";")
    if not sql:
        raise HTTPException(status_code=400, detail="sql must not be empty")

    settings = get_settings()
    provider = provider_from_connection(connection)
    try:
        ok, err, is_dml = validate_syntax(sql, provider.sqlglot_dialect())
        if not ok:
            raise HTTPException(
                status_code=400,
                detail=err or ("DML blocked" if is_dml else "Invalid SQL"),
            )

        try:
            await provider.explain_query(sql)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"EXPLAIN failed: {exc}"
            ) from exc

        results = await provider.execute_readonly(
            sql, max_rows=settings.max_result_rows
        )
        return ExecuteSqlOut(
            sql=sql,
            columns=list(results.get("columns") or []),
            rows=list(results.get("rows") or []),
            row_count=int(results.get("row_count") or 0),
        )
    finally:
        await provider.close()


@router.post("/sync", response_model=AgentStateOut)
async def query_sync(body: QueryRequest, db: DbSession) -> dict[str, Any]:
    connection = await _ensure_connection(db, body.connection_id)
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")
    session_id = await _ensure_session(db, body.session_id, body.connection_id)
    history = [t.model_dump() for t in body.conversation_history]
    try:
        result = await run_query(
            db,
            connection,
            body.question,
            conversation_history=history,
            session_id=session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    return dict(result)


@router.post("")
async def query_stream(body: QueryRequest, db: DbSession) -> EventSourceResponse:
    connection = await _ensure_connection(db, body.connection_id)
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")
    session_id = await _ensure_session(db, body.session_id, body.connection_id)
    history = [t.model_dump() for t in body.conversation_history]

    async def event_generator():
        try:
            async for item in stream_query(
                db,
                connection,
                body.question,
                conversation_history=history,
                session_id=session_id,
            ):
                yield _normalize_sse_item(item if isinstance(item, dict) else {"data": item})
        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}
            yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())
