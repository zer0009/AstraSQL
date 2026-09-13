from __future__ import annotations

import json
import re
from typing import Any, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from src.agent.state import AgentState
from src.config.settings import get_settings


def extract_json(text: str) -> Any:
    """Parse JSON from an LLM response, stripping markdown fences if present."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", cleaned)
        if match:
            return json.loads(match.group(0))
        raise


def message_text(response: Any) -> str:
    """Normalize a chat model response to plain text."""
    if isinstance(response, AIMessage):
        content = response.content
    else:
        content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def get_configurable(config: Optional[RunnableConfig]) -> dict[str, Any]:
    if not config:
        return {}
    return dict(config.get("configurable") or {})


def append_step(
    state: AgentState,
    name: str,
    detail: str,
    **extra: Any,
) -> list[dict]:
    steps = list(state.get("steps") or [])
    event: dict[str, Any] = {"name": name, "detail": detail}
    event.update(extra)
    steps.append(event)
    return steps


def confidence_to_float(confidence: str | None) -> float:
    mapping = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.2}
    return mapping.get((confidence or "").upper(), 0.0)


def compute_confidence(retries: int, row_count: int) -> str:
    """Deterministic confidence from retries and result size."""
    if retries == 0 and row_count > 0:
        return "HIGH"
    if retries == 1 or row_count == 0:
        return "MEDIUM"
    return "LOW"


def max_retries() -> int:
    return int(get_settings().max_retries)


_RETRY_FIX_HINTS: dict[str, str] = {
    "WRONG_TABLE": (
        "Wrong table(s) selected. Re-map each entity in the question to its "
        "dedicated lookup/reference table in the schema. Prefer tables with "
        "name/title/label/code/display_name columns over raw *_id FKs."
    ),
    "ENTITY_MAPPING": (
        "Entity mapping error. JOIN the lookup table that holds the human-readable "
        "name for the dimension the question asks about; do not group/filter by a "
        "raw *_id foreign key as a substitute."
    ),
    "CROSS_DIMENSIONAL": (
        "Cross-dimensional comparison missing. Implement a proper self-join or "
        "cross-comparison between two instances of the same entity — do not collapse "
        "into a single-dimension GROUP BY."
    ),
    "WRONG_COLUMN": (
        "Column does not exist or was hallucinated. Use only columns present in the "
        "provided schema; qualify with table aliases."
    ),
    "SYNTAX_ERROR": (
        "SQL syntax/parse error. Fix dialect-specific syntax while preserving the "
        "intended logic."
    ),
    "AGGREGATION_ERROR": (
        "Aggregation/GROUP BY mismatch. Every non-aggregated SELECT column must "
        "appear in GROUP BY; fix HAVING vs WHERE usage."
    ),
    "TYPE_MISMATCH": (
        "PostgreSQL type/operator mismatch. Do NOT use ->> or -> on varchar/text/"
        "character varying columns — SELECT the column directly (e.g. rcs.name). "
        "Only use JSON operators on columns whose schema type is json or jsonb."
    ),
    "EXECUTION_ERROR": (
        "Database execution failed. Fix the exact error from the engine while "
        "keeping the query aligned with the schema and question."
    ),
    "OTHER": (
        "Fix the SQL so it executes successfully against the schema and answers "
        "the original question."
    ),
}


def classify_retry_type(
    *,
    error: str = "",
    issues: list | None = None,
    error_type: str | None = None,
    is_syntax: bool = False,
) -> str:
    """Map validator/executor failures to a typed retry category."""
    if error_type:
        normalized = str(error_type).strip().upper()
        if normalized in _RETRY_FIX_HINTS and normalized != "OTHER":
            return normalized
        if normalized == "NONE":
            return "OTHER"

    if is_syntax:
        return "SYNTAX_ERROR"

    blob = " ".join(
        [error or ""]
        + [str(i) for i in (issues or [])]
    ).lower()

    if any(
        token in blob
        for token in (
            "entity mapping",
            "lookup table",
            "human-readable",
            "raw *_id",
            "raw _id",
            "surrogate",
        )
    ):
        return "ENTITY_MAPPING"
    if any(
        token in blob
        for token in (
            "cross-dimensional",
            "cross dimensional",
            "self-join",
            "self join",
            "two instances",
        )
    ):
        return "CROSS_DIMENSIONAL"
    if any(
        token in blob
        for token in (
            "wrong table",
            "missing table",
            "table does not exist",
            "relation does not exist",
            "undefined table",
        )
    ):
        return "WRONG_TABLE"
    if any(
        token in blob
        for token in (
            "operator does not exist",
            "character varying ->>",
            "text ->>",
            "varchar ->>",
            "->> unknown",
            "json operator",
            "type mismatch",
        )
    ):
        return "TYPE_MISMATCH"
    if any(
        token in blob
        for token in (
            "column",
            "does not exist",
            "unknown column",
            "undefined column",
            "no such column",
        )
    ):
        return "WRONG_COLUMN"
    if any(
        token in blob
        for token in (
            "group by",
            "must appear in the group",
            "aggregate",
            "aggregation",
        )
    ):
        return "AGGREGATION_ERROR"
    if any(
        token in blob
        for token in ("syntax", "parse", "parser")
    ):
        return "SYNTAX_ERROR"
    return "EXECUTION_ERROR" if error else "OTHER"


def build_retry_context(
    *,
    previous_sql: str,
    error: str,
    prior_context: str = "",
    retry_type: str = "OTHER",
) -> str:
    hint = _RETRY_FIX_HINTS.get(
        (retry_type or "OTHER").upper(),
        _RETRY_FIX_HINTS["OTHER"],
    )
    block = (
        f"Retry type: [{(retry_type or 'OTHER').upper()}]\n"
        f"Previous SQL: [{previous_sql}]\n"
        f"Error: [{error}]\n"
        f"Correction needed: {hint}"
    )
    if prior_context and prior_context.strip():
        return f"{prior_context.strip()}\n\n---\n\n{block}"
    return block
