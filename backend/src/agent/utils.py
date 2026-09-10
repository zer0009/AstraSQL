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


def build_retry_context(
    *,
    previous_sql: str,
    error: str,
    prior_context: str = "",
) -> str:
    block = (
        f"Previous SQL: [{previous_sql}]\n"
        f"Error: [{error}]\n"
        "Correction needed: Fix the SQL so it executes successfully against the schema."
    )
    if prior_context and prior_context.strip():
        return f"{prior_context.strip()}\n\n---\n\n{block}"
    return block
