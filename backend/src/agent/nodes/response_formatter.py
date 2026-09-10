from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.prompts.formatter import render_formatter_prompt
from src.agent.state import AgentState
from src.agent.utils import (
    append_step,
    compute_confidence,
    extract_json,
    message_text,
)
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider


def _result_summary(results: dict | None, error: str | None) -> str:
    if error:
        return f"Query failed: {error}"
    if not results:
        return "No results available"
    row_count = int(results.get("row_count") or 0)
    rows = results.get("rows") or []
    columns = results.get("columns") or []
    if row_count == 0:
        return "Empty result set (0 rows)"
    preview_rows = rows[:3]
    preview = []
    for row in preview_rows:
        if isinstance(row, dict):
            preview.append(row)
        elif isinstance(row, (list, tuple)) and columns:
            preview.append(dict(zip(columns, row)))
        else:
            preview.append(row)
    try:
        preview_text = json.dumps(preview, default=str)
    except TypeError:
        preview_text = str(preview)
    if row_count == 1 and len(columns) <= 3:
        return f"Aggregation result: {preview_text}"
    return f"{row_count} rows returned. First 3 rows: {preview_text}"


async def response_formatter(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Build the user-facing answer and deterministic confidence score."""
    settings = get_settings()
    question = state.get("question") or ""
    sql = (state.get("corrected_sql") or state.get("sql") or "").strip()
    results = state.get("results") or {}
    error = state.get("error")
    retries = int(state.get("retries") or 0)
    row_count = int((results or {}).get("row_count") or 0)

    if error and not results:
        confidence = "LOW" if retries >= 2 else "MEDIUM"
        answer = (
            "I couldn't complete this query successfully. "
            f"Last error: {error}"
        )
        return {
            "confidence": confidence,
            "answer": answer,
            "key_finding": "Query did not succeed",
            "assumption": None,
            "follow_ups": [
                "Can you rephrase the question with more detail?",
                "Which tables or metrics should I focus on?",
            ],
            "steps": append_step(
                state,
                "response_formatted",
                f"Failure response (confidence={confidence})",
                confidence=confidence,
            ),
        }

    confidence = compute_confidence(retries, row_count)
    summary = _result_summary(results if not error else None, error)

    try:
        system = render_formatter_prompt(question, sql, summary)
        llm = get_llm_provider().get_chat_model(
            temperature=0.3,
            max_tokens=settings.llm_max_tokens,
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(content="Format the response as JSON only."),
            ],
            config=config,
        )
        parsed = extract_json(message_text(response))
        answer = str(parsed.get("answer") or "").strip() or summary
        key_finding = str(parsed.get("key_finding") or "").strip()
        assumption = parsed.get("assumption")
        if assumption is not None:
            assumption = str(assumption).strip() or None
        follow_ups = parsed.get("follow_up_suggestions") or parsed.get(
            "follow_ups"
        ) or []
        if not isinstance(follow_ups, list):
            follow_ups = [str(follow_ups)]
        follow_ups = [str(x) for x in follow_ups if x]
    except Exception as exc:
        answer = (
            f"Query returned {row_count} row(s). "
            f"(Formatter fallback: {exc})"
        )
        key_finding = f"{row_count} row(s)" if row_count else "No rows"
        assumption = None
        follow_ups = []

    return {
        "confidence": confidence,
        "answer": answer,
        "key_finding": key_finding,
        "assumption": assumption,
        "follow_ups": follow_ups,
        "steps": append_step(
            state,
            "response_formatted",
            f"Formatted answer (confidence={confidence})",
            confidence=confidence,
        ),
    }
