from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.agent.runner import run_query, stream_query
from src.agent.sql_guards import validate_syntax
from src.api.deps import DbSession
from src.api.schemas import (
    AgentStateOut,
    ExecuteSqlOut,
    ExecuteSqlRequest,
    QueryRequest,
    RefineRequest,
    RememberDefinitionRequest,
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
async def query_sync(body: QueryRequest, db: DbSession) -> Any:
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
            evidence=(body.evidence or "").strip(),
        )
    except (ValueError, RuntimeError, OSError) as exc:
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
    evidence = (body.evidence or "").strip()

    async def event_generator():
        try:
            async for item in stream_query(
                db,
                connection,
                body.question,
                conversation_history=history,
                session_id=session_id,
                evidence=evidence,
            ):
                yield _normalize_sse_item(item if isinstance(item, dict) else {"data": item})
        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}
            yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())


@router.post("/refine")
async def query_refine(body: RefineRequest, db: DbSession) -> EventSourceResponse:
    """Resume a prior run with a chosen reading — skips retrieval and re-asking.

    When the snapshot stores gate ``readings`` (label → SQL), the chosen chip
    reuses that SQL (1 LLM call at most for formatting). Otherwise falls back
    to regenerating with the choice as an assumption.
    """
    from src.agent.execution_gate import resolve_reading_sql
    from src.agent.runner import _initial_state, _persist_history, _run_config
    from src.storage.repositories.snapshots import load_run_snapshot, snapshot_to_state

    snap = await load_run_snapshot(db, body.run_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Run snapshot not found")
    connection_id = body.connection_id or snap.connection_id
    connection = await _ensure_connection(db, connection_id)
    if snap.connection_id != connection.id:
        raise HTTPException(status_code=400, detail="Snapshot connection mismatch")
    session_id = await _ensure_session(
        db, body.session_id or snap.session_id, connection.id
    )
    choice = (body.choice or "").strip()
    if not choice:
        raise HTTPException(status_code=400, detail="choice must not be empty")

    base = snapshot_to_state(snap)
    question = str(base.get("question") or snap.question)
    ambiguity = base.get("ambiguity") if isinstance(base.get("ambiguity"), dict) else {}
    readings = list(ambiguity.get("readings") or [])
    # Fallback for older snapshots: pair chip labels with cluster SQL by index.
    if not readings:
        labels = list(
            ambiguity.get("alternatives")
            or ambiguity.get("options")
            or []
        )
        clusters = list(ambiguity.get("clusters") or [])
        for i, cluster in enumerate(clusters):
            if not isinstance(cluster, dict):
                continue
            sql = str(cluster.get("sql") or "").strip()
            if not sql:
                continue
            label = (
                str(labels[i]).strip()
                if i < len(labels) and str(labels[i]).strip()
                else f"Reading {i + 1}"
            )
            if label.lower().startswith("other"):
                continue
            readings.append({"label": label, "sql": sql})
    chosen_sql = resolve_reading_sql(choice, readings)
    context = (
        dict(base["context"])
        if isinstance(base.get("context"), dict)
        else {}
    )
    if chosen_sql:
        context["verified_sql"] = chosen_sql

    async def event_generator():
        from src.observability.usage import UsageTracker, track_usage
        import src.agent.runner as runner_mod

        provider = provider_from_connection(connection)
        tracker = UsageTracker()
        try:
            with track_usage(tracker):
                graph = runner_mod.get_graph()
                initial = _initial_state(
                    connection,
                    question,
                    conversation_history=[],
                    run_id=snap.id,
                    allow_clarify=False,
                    refine_choice=choice,
                    context=context or None,
                    extra={
                        "assumption": choice,
                        "used_golden": False,
                        "intent": "SQL_QUERY",
                        "follow_ups": [],
                        "clarification_options": [],
                        "ambiguity": {
                            "should_clarify": False,
                            "status": "clear",
                            "needs_execution_gate": False,
                            "alternatives": [],
                            "readings": [],
                            "decision_why": (
                                "refine_reading" if chosen_sql else "refine_regenerate"
                            ),
                        },
                    },
                )
                config = _run_config(db, connection, provider)
                yield {
                    "event": "start",
                    "data": json.dumps(
                        {
                            "connection_id": connection.id,
                            "question": question,
                            "run_id": snap.id,
                            "refine": True,
                            "reuse_sql": bool(chosen_sql),
                        }
                    ),
                }
                final_state: dict[str, Any] = dict(initial)
                async for chunk in graph.astream(
                    initial, config=config, stream_mode="updates"
                ):
                    if not isinstance(chunk, dict):
                        continue
                    for node_name, update in chunk.items():
                        if not isinstance(update, dict):
                            continue
                        final_state.update(update)
                        yield {
                            "event": "node",
                            "data": json.dumps(
                                {"node": node_name, **update}, default=str
                            ),
                        }
                final_state["usage_summary"] = {
                    "by_stage": tracker.summary_by_stage(),
                    "cost_usd": tracker.total_cost(),
                    "calls": len(tracker.records),
                }
                try:
                    history = await _persist_history(
                        db, connection, final_state, session_id=session_id
                    )
                    if history is not None:
                        final_state["history_id"] = history.id
                except Exception:
                    pass
                done = {
                    "answer": final_state.get("answer"),
                    "sql": final_state.get("corrected_sql")
                    or final_state.get("sql"),
                    "results": final_state.get("results"),
                    "assumption": final_state.get("assumption") or choice,
                    "trust_level": final_state.get("trust_level"),
                    "confidence": final_state.get("confidence"),
                    "key_finding": final_state.get("key_finding"),
                    "run_id": snap.id,
                    "history_id": final_state.get("history_id"),
                    "clarification_options": [],
                    "follow_ups": final_state.get("follow_ups") or [],
                    "usage_summary": final_state.get("usage_summary"),
                }
                yield {"event": "result", "data": json.dumps(done, default=str)}
                yield {"event": "done", "data": json.dumps(done, default=str)}
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"message": str(exc)}),
            }
            yield {"event": "done", "data": "{}"}
        finally:
            await provider.close()

    return EventSourceResponse(event_generator())


@router.post("/remember")
async def remember_definition(
    body: RememberDefinitionRequest, db: DbSession
) -> dict[str, Any]:
    """Save a chosen reading as a business rule so the ambiguity does not recur."""
    from src.context.business_rules import BusinessRulesStore

    connection = await _ensure_connection(db, body.connection_id)
    text = (body.definition or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="definition must not be empty")
    term = (body.term or "").strip()
    content = f"{term}: {text}" if term else text
    store = BusinessRulesStore()
    rule = await store.create(db, connection.id, content)
    await db.commit()
    await db.refresh(rule)
    return {
        "ok": True,
        "rule_id": rule.id,
        "content": content,
    }
