from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.agent.runner import run_query, stream_query
from src.api.deps import DbSession
from src.api.schemas import AgentStateOut, QueryRequest
from src.storage.models import Connection

router = APIRouter(tags=["query"])


async def _ensure_connection(db: DbSession, connection_id: str) -> Connection:
    conn = await db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


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


@router.post("/sync", response_model=AgentStateOut)
async def query_sync(body: QueryRequest, db: DbSession) -> dict[str, Any]:
    connection = await _ensure_connection(db, body.connection_id)
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")
    try:
        result = await run_query(db, connection, body.question)
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

    async def event_generator():
        try:
            async for item in stream_query(db, connection, body.question):
                yield _normalize_sse_item(item if isinstance(item, dict) else {"data": item})
        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}
            yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())
